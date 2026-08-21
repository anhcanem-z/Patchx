// frida_loader.js
const fs = require('fs');

function loadAndRunHooks(jsonPath) {
    var configFile = fs.readFileSync(jsonPath, 'utf8');
    var config = JSON.parse(configFile);

    console.log("[*] Loading Frida Config for Package: " + config.metadata.target_package);
    console.log("[*] Total active rules: " + config.hooks.length);

    config.hooks.forEach(function(rule) {
        if (!rule.enabled) return;

        console.log("[+] Executing Rule ID: " + rule.id + " (" + rule.category + ")");
        try {
            // Thực thi trực tiếp khối lệnh JS sinh sẵn từ JSON
            eval(rule.frida_script);
        } catch (err) {
            console.error("[-] Failed to eval rule: " + rule.id + " | Error: " + err.message);
        }
    });
}

// Gọi thực thi
loadAndRunHooks("frida_hooks_config.json");
