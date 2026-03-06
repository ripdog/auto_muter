// KWin Script: Mute Unfocused Event Sender (main.js)
// Version 0.9 - Uses QTimer for timed operations
    
const DBUS_HELPER_SERVICE_NAME_STR = "com.example.FocusAudioManager"; 
const DBUS_HELPER_OBJECT_PATH_STR = "/com/example/FocusAudioManager"; 
const DBUS_HELPER_INTERFACE_NAME_STR = "com.example.FocusAudioManager"; 
const DBUS_METHOD_UPDATE_FOCUS_STR = "UpdateFocus";
const SCRIPT_LIFETIME_MS = 60 * 1000; // 60 seconds

var initialFocusTimer = null; // To store QTimer object
var selfStopMainTimer = null;  // To store QTimer object for self-stopping
var isScriptFunctionalityStopped = false; // Flag to prevent operations after stop

function kwinLog(message) {
    //print("[MuteUnfocusedSender] " + new Date().toISOString() + ": " + message);
}
    
function sendFocusedPIDToHelper(pid) {
    if (typeof pid !== 'number' || isNaN(pid)) {
        // kwinLog("Invalid or NaN PID detected. Type: " + typeof pid + ", Value: " + pid + ". Sending -1 instead.");
        pid = -1;
    }
    // kwinLog("Attempting to send PID: " + pid + " to D-Bus service: " + DBUS_HELPER_SERVICE_NAME_STR);
    
    try {
        callDBus(
            DBUS_HELPER_SERVICE_NAME_STR,
            DBUS_HELPER_OBJECT_PATH_STR,
            DBUS_HELPER_INTERFACE_NAME_STR, 
            DBUS_METHOD_UPDATE_FOCUS_STR,
            pid, 
            function(reply) { 
                // kwinLog("D-Bus call to UpdateFocus callback invoked. Reply (if any from D-Bus layer): " + JSON.stringify(reply));
            }
        );
        // kwinLog("D-Bus call to UpdateFocus initiated for PID: " + pid);
    } catch (e) {
        kwinLog("CRITICAL: Error making D-Bus call with global callDBus: " + e.toString());
    }
}

function onWindowActivated(window) {
    if (isScriptFunctionalityStopped) return;

    if (window && typeof window.pid === 'number') {
        // kwinLog("Window activated: '" + window.caption + "', PID: " + window.pid);
        sendFocusedPIDToHelper(window.pid);
    } else if (window) {
        // kwinLog("Window activated: '" + window.caption + "', PID not available. Sending -1.");
        sendFocusedPIDToHelper(-1); 
    } else {
        // kwinLog("Window activated, but 'window' object is null. Desktop focused? Sending -1.");
        sendFocusedPIDToHelper(-1); 
    }
}
    
try {
    workspace.windowActivated.connect(onWindowActivated);
    // kwinLog("Connected to workspace.windowActivated signal.");
} catch (e) {
    kwinLog("CRITICAL: Error connecting to workspace.windowActivated: " + e.toString());
}
    
function sendInitialFocusState() {
    if (isScriptFunctionalityStopped) return;
    // kwinLog("Attempting to send initial focus state...");
    let currentWindow = workspace.activeWindow; 
    if (currentWindow && typeof currentWindow.pid === 'number') {
        // kwinLog("Initial active window: '" + currentWindow.caption + "', PID: " + currentWindow.pid);
        sendFocusedPIDToHelper(currentWindow.pid);
    } else {
        // kwinLog("No active window with PID on startup. Sending -1.");
        sendFocusedPIDToHelper(-1);
    }
}

// function stopScriptFunctionality() {
//     kwinLog("Stopping script functionality after " + (SCRIPT_LIFETIME_MS / 1000) + " seconds.");
//     isScriptFunctionalityStopped = true; // Set flag to stop operations
//     try {
//         if (typeof workspace !== 'undefined' && typeof workspace.windowActivated !== 'undefined' && typeof workspace.windowActivated.disconnect === 'function') {
//              workspace.windowActivated.disconnect(onWindowActivated);
//              kwinLog("Disconnected from workspace.windowActivated signal.");
//         } else {
//             kwinLog("Could not directly disconnect workspace.windowActivated. Operations will cease due to flag.");
//         }
//
//         // Stop timers if they are active
//         if (initialFocusTimer && typeof initialFocusTimer.stop === 'function') {
//             initialFocusTimer.stop();
//             kwinLog("Stopped initialFocusTimer.");
//         }
//         if (selfStopMainTimer && typeof selfStopMainTimer.stop === 'function') {
//             selfStopMainTimer.stop(); // This timer would have just fired, but good practice
//             kwinLog("Stopped selfStopMainTimer.");
//         }
//
//     } catch (e) {
//         kwinLog("Error during script functionality stop: " + e.toString());
//     }
//     kwinLog("Script operations effectively ceased.");
// }
    
// Setup initial focus send using QTimer
try {
    if (typeof QTimer === "function") { // Check if QTimer constructor is available
        initialFocusTimer = new QTimer();
        initialFocusTimer.singleShot = true;
        initialFocusTimer.timeout.connect(sendInitialFocusState);
        initialFocusTimer.start(2500); // 2.5 seconds delay
        // kwinLog("QTimer scheduled for initial focus state.");

        // // Setup self-stop timer using QTimer
        // selfStopMainTimer = new QTimer();
        // selfStopMainTimer.singleShot = true;
        // selfStopMainTimer.timeout.connect(stopScriptFunctionality);
        // selfStopMainTimer.start(SCRIPT_LIFETIME_MS);
        // kwinLog("QTimer scheduled for self-stop in " + (SCRIPT_LIFETIME_MS / 1000) + " seconds.");

    } else {
        // kwinLog("QTimer is not available. Cannot schedule timed operations. Attempting immediate initial focus send.");
        sendInitialFocusState(); // Fallback
        // kwinLog("Self-stopping mechanism will not be armed.");
    }
} catch (e) {
    // kwinLog("Error setting up QTimer: " + e.toString() + ". Attempting immediate initial focus send.");
    sendInitialFocusState(); // Fallback
    // kwinLog("Self-stopping mechanism will not be armed due to QTimer error.");
}
    
// kwinLog("KWin script setup complete.");
