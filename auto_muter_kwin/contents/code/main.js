// KWin Script: Mute Unfocused Event Sender (main.js)
// Version 1.0 - Uses QTimer for timed operations
    
const DBUS_HELPER_SERVICE_NAME_STR = "com.example.FocusAudioManager"; 
const DBUS_HELPER_OBJECT_PATH_STR = "/com/example/FocusAudioManager"; 
const DBUS_HELPER_INTERFACE_NAME_STR = "com.example.FocusAudioManager"; 
const DBUS_METHOD_UPDATE_FOCUS_STR = "UpdateFocus";

var initialFocusTimer = null; // To store QTimer object
var isScriptFunctionalityStopped = false; // Flag to prevent operations after stop

function sendFocusedPIDToHelper(pid) {
    if (typeof pid !== 'number' || isNaN(pid)) {
        pid = -1;
    }
    
    try {
        callDBus(
            DBUS_HELPER_SERVICE_NAME_STR,
            DBUS_HELPER_OBJECT_PATH_STR,
            DBUS_HELPER_INTERFACE_NAME_STR, 
            DBUS_METHOD_UPDATE_FOCUS_STR,
            pid, 
            function(reply) {}
        );
    } catch (e) {
        console.error("CRITICAL: Error making D-Bus call with global callDBus: " + e.toString());
    }
}

function onWindowActivated(window) {
    if (isScriptFunctionalityStopped) return;

    if (window && typeof window.pid === 'number') {
        sendFocusedPIDToHelper(window.pid);
    } else if (window) {
        sendFocusedPIDToHelper(-1); 
    } else {
        sendFocusedPIDToHelper(-1); 
    }
}
    
try {
    workspace.windowActivated.connect(onWindowActivated);
} catch (e) {
    console.error("CRITICAL: Error connecting to workspace.windowActivated: " + e.toString());
}
    
function sendInitialFocusState() {
    if (isScriptFunctionalityStopped) return;
    let currentWindow = workspace.activeWindow; 
    if (currentWindow && typeof currentWindow.pid === 'number') {
        sendFocusedPIDToHelper(currentWindow.pid);
    } else {
        sendFocusedPIDToHelper(-1);
    }
}

// Setup initial focus send using QTimer
try {
    if (typeof QTimer === "function") { // Check if QTimer constructor is available
        initialFocusTimer = new QTimer();
        initialFocusTimer.singleShot = true;
        initialFocusTimer.timeout.connect(sendInitialFocusState);
        initialFocusTimer.start(2500); // 2.5 seconds delay
    } else {
        sendInitialFocusState(); // Fallback
    }
} catch (e) {
    console.error("Error setting up QTimer: " + e.toString() + ". Attempting immediate initial focus send.");
    sendInitialFocusState(); // Fallback
}
