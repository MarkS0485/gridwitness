// Progressive enhancement for the survey upload form. The form works without this script (a plain
// multipart file input); this adds a drag-and-drop zone, an accumulating file list with per-file
// remove, and client-side count/extension guards. The server re-validates everything regardless.
(function () {
    "use strict";

    var MAX_FILES = 100;
    var ALLOWED = [".csv", ".txt", ".tsv", ".pqd", ".pqdif"];

    var dropzone = document.getElementById("dropzone");
    var input = document.getElementById("file-input");
    var list = document.getElementById("file-list");
    var count = document.getElementById("file-count");
    if (!dropzone || !input) return;

    // A DataTransfer is the browser-blessed way to build the FileList the input submits, and lets us
    // accumulate across several drops and remove individual files.
    var bag = new DataTransfer();

    function ext(name) {
        var dot = name.lastIndexOf(".");
        return dot < 0 ? "" : name.slice(dot).toLowerCase();
    }

    function humanSize(bytes) {
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1048576) return (bytes / 1024).toFixed(0) + " KB";
        return (bytes / 1048576).toFixed(1) + " MB";
    }

    function render() {
        list.innerHTML = "";
        for (var i = 0; i < bag.files.length; i++) {
            (function (idx, file) {
                var li = document.createElement("li");
                li.className = "flex items-center justify-between gap-3 px-3 py-1.5 rounded bg-white border border-gray-200";
                var label = document.createElement("span");
                label.className = "truncate";
                label.textContent = file.name + "  ·  " + humanSize(file.size);
                var btn = document.createElement("button");
                btn.type = "button";
                btn.className = "text-tsgb-red hover:underline shrink-0";
                btn.setAttribute("aria-label", "Remove " + file.name);
                btn.textContent = "remove";
                btn.addEventListener("click", function () { removeAt(idx); });
                li.appendChild(label);
                li.appendChild(btn);
                list.appendChild(li);
            })(i, bag.files[i]);
        }
        input.files = bag.files;
        var n = bag.files.length;
        count.textContent = n === 0 ? "" : n + " file" + (n === 1 ? "" : "s") + " ready" +
            (n > MAX_FILES ? " — that's over the 100-file limit, please remove some." : "");
        count.style.color = n > MAX_FILES ? "#C8102E" : "";
    }

    function removeAt(idx) {
        var next = new DataTransfer();
        for (var i = 0; i < bag.files.length; i++) {
            if (i !== idx) next.items.add(bag.files[i]);
        }
        bag = next;
        render();
    }

    function add(files) {
        for (var i = 0; i < files.length; i++) {
            var f = files[i];
            if (ALLOWED.indexOf(ext(f.name)) === -1) continue;      // skip unsupported types quietly
            if (bag.files.length >= MAX_FILES) break;
            bag.items.add(f);
        }
        render();
    }

    // Native picker via the hidden input (the label wraps it, so a click already opens it).
    input.addEventListener("change", function () {
        add(input.files);
    });

    ["dragenter", "dragover"].forEach(function (ev) {
        dropzone.addEventListener(ev, function (e) {
            e.preventDefault();
            dropzone.classList.add("border-tsgb-navy");
        });
    });
    ["dragleave", "drop"].forEach(function (ev) {
        dropzone.addEventListener(ev, function (e) {
            e.preventDefault();
            dropzone.classList.remove("border-tsgb-navy");
        });
    });
    dropzone.addEventListener("drop", function (e) {
        if (e.dataTransfer && e.dataTransfer.files) add(e.dataTransfer.files);
    });
})();
