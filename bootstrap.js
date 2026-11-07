// Windows Script Host entry point for a fresh Fenn installation.
var shell = new ActiveXObject("WScript.Shell");
var files = new ActiveXObject("Scripting.FileSystemObject");
var env = shell.Environment("Process");
var folder = files.GetParentFolderName(WScript.ScriptFullName);
var pythonUrl = "https://www.python.org/downloads/windows/";

function json(value) {
    if (typeof value === "string") {
        return '"' + value.replace(/[\\"\x00-\x1f\x7f-\uffff]/g, function (character) {
            var hex = character.charCodeAt(0).toString(16);
            return "\\u" + ("0000" + hex).slice(-4);
        }) + '"';
    }
    if (typeof value !== "object") return String(value);
    var parts = [];
    if (value instanceof Array) {
        for (var i = 0; i < value.length; i++) parts.push(json(value[i]));
        return "[" + parts.join(",") + "]";
    }
    for (var key in value) {
        if (value.hasOwnProperty(key)) parts.push(json(key) + ":" + json(value[key]));
    }
    return "{" + parts.join(",") + "}";
}

function send(message) {
    WScript.StdOut.WriteLine(json(message));
}

function show(title, detail, working) {
    var children = [
        {type: "text", size: "title", text: title},
        {type: "text", color: "dim", wrap: true, text: detail}
    ];
    if (!working) {
        children.push({type: "button", id: "setup", label: "Set up Drop-to-Convert",
                       icon: "download-simple", primary: true});
        children.push({type: "button", id: "python-download", label: "Get Python manually"});
    }
    send({type: "page", view: {type: "card", padding: 12, gap: 8, children: children}});
}

function setupCommand(stage) {
    // Pass local paths through environment variables to avoid building a shell command from them.
    return shell.Run("%SystemRoot%\\System32\\cmd.exe /d /c bootstrap-tools.cmd " + stage, 0, true);
}

function findPython() {
    var roots = [env("LOCALAPPDATA") + "\\Programs\\Python", env("ProgramFiles")];
    var candidates = [];
    for (var i = 0; i < roots.length; i++) {
        if (!roots[i] || !files.FolderExists(roots[i])) continue;
        var dirs = new Enumerator(files.GetFolder(roots[i]).SubFolders);
        for (; !dirs.atEnd(); dirs.moveNext()) {
            var directory = dirs.item();
            if (/^Python[0-9]/i.test(directory.Name)) candidates.push(directory.Path + "\\python.exe");
        }
    }
    var path = env("PATH").split(";");
    for (var j = 0; j < path.length; j++) {
        var entry = path[j].replace(/^"|"$/g, "");
        if (entry && !/\\Microsoft\\WindowsApps\\?$/i.test(entry)) {
            candidates.push(files.BuildPath(entry, "python.exe"));
        }
    }
    for (var k = 0; k < candidates.length; k++) {
        if (files.FileExists(candidates[k])) {
            env("DTC_SETUP_PYTHON") = candidates[k];
            if (setupCommand("probe") === 0) return true;
        }
    }
    return false;
}

function install() {
    if (setupCommand("prepare") !== 0) throw new Error("Could not create the plugin setup folder.");
    if (!findPython()) {
        show("Installing Python", "Windows Package Manager will download Python. Follow any Windows setup prompts.", true);
        setupCommand("python");
        if (!findPython()) throw new Error("Python setup did not finish. Install Python manually or retry.");
    }
    show("Installing conversion tools", "Downloading Pillow, PDFium and FFmpeg from the Python Package Index.", true);
    if (setupCommand("runtime") !== 0) {
        throw new Error("The conversion tools could not be set up. Check your connection and retry.");
    }
}

function field(line, key) {
    // Fenn uses plain ASCII tokens for protocol types, kinds and control IDs.
    var match = new RegExp('(?:^|[{,])\\s*"' + key + '"\\s*:\\s*"([a-z_-]+)"').exec(line);
    return match ? match[1] : "";
}

shell.CurrentDirectory = folder;
send({type: "tile", view: {type: "column", align: "center", justify: "center", children: [
    {type: "icon", icon: "download-simple", color: "accent"}
]}});
show("Set up Drop-to-Convert", "Setup downloads the conversion tools and installs Python for your Windows account if needed.", false);
while (!WScript.StdIn.AtEndOfStream) {
    var line = WScript.StdIn.ReadLine();
    var type = field(line, "type");
    if (type === "shutdown") break;
    if (type !== "event" || field(line, "kind") !== "click") continue;
    var id = field(line, "id");
    if (id === "python-download") {
        send({type: "open", target: pythonUrl});
    } else if (id === "setup") {
        try {
            install();
            // launch.cmd starts the converter on the same Fenn connection.
            WScript.Quit(10);
        } catch (error) {
            show("Setup needs attention", error.message + " See setup.log in the plugin data folder.", false);
        }
    }
}
