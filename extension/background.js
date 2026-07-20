let isRecording = false;
let sessionSteps = [];
let recordingTabId = null;
let appTabId = null;

// Listen for messages from content scripts
chrome.runtime.onMessage.addListener(function(request, sender, sendResponse) {
  if (request.type === "CHECK_RECORDING_STATUS") {
    // Only return active if this is the tab currently being recorded
    const active = isRecording && sender.tab && (sender.tab.id === recordingTabId);
    sendResponse({ isRecording: active });
    return true;
  }

  if (request.type === "START_RECORDING_SESSION") {
    isRecording = true;
    sessionSteps = [];
    appTabId = sender.tab ? sender.tab.id : null;

    console.log("Starting session. App tab ID:", appTabId);

    // Open target URL in a new tab
    chrome.tabs.create({ url: request.url }, function(tab) {
      recordingTabId = tab.id;
      console.log("Recording target tab created with ID:", recordingTabId);
    });
    
    sendResponse({ status: "success" });
    return true;
  }

  if (request.type === "CAPTURE_STEP") {
    if (!isRecording) return;
    
    // Capture the screenshot of the active visible tab
    chrome.tabs.captureVisibleTab(null, { format: "png" }, function(dataUrl) {
      if (chrome.runtime.lastError) {
        console.error("Screenshot capture error:", chrome.runtime.lastError.message);
        return;
      }
      
      const step = {
        order_index: sessionSteps.length,
        caption: request.caption,
        screenshot_base64: dataUrl,
        click_x_percent: request.x,
        click_y_percent: request.y,
        click_width_percent: request.width || 0,
        click_height_percent: request.height || 0,
        is_typing: request.is_typing || false
      };
      
      sessionSteps.push(step);
      console.log(`Step ${step.order_index + 1} captured: "${step.caption}"`);
    });
    
    return true;
  }

  if (request.type === "STOP_RECORDING_SESSION") {
    isRecording = false;
    
    // Tell content script to clean up
    if (recordingTabId) {
      chrome.tabs.sendMessage(recordingTabId, { type: "RECORDING_STOPPED" }, function() {
        // Ignore errors if tab was closed
        if (chrome.runtime.lastError) {}
      });
    }

    if (request.save && sessionSteps.length > 0) {
      console.log("Saving recording. Steps count:", sessionSteps.length);
      
      // Upload to backend API
      const timestamp = new Date().toLocaleString();
      const payload = {
        title: `Recorded Walkthrough (${timestamp})`,
        description: "Created in real-time using the Scrib Browser Extension.",
        steps: sessionSteps
      };

      fetch("http://localhost:8502/api/guides", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      })
      .then(resp => {
        if (!resp.ok) throw new Error("Backend upload failed");
        return resp.json();
      })
      .then(data => {
        console.log("Upload success, guide_id:", data.guide_id);
        
        // Clean up and focus/redirect app tab
        closeRecordingAndRedirect(data.guide_id);
      })
      .catch(err => {
        console.error("Error saving guide:", err);
        // Fallback: don't close, alert user or just clean up
        closeRecordingAndRedirect(null);
      });
    } else {
      console.log("Discarding recording.");
      closeRecordingAndRedirect(null);
    }
    
    return true;
  }
});

function closeRecordingAndRedirect(guideId) {
  // Close the recording tab
  if (recordingTabId) {
    chrome.tabs.remove(recordingTabId, function() {
      if (chrome.runtime.lastError) {}
    });
    recordingTabId = null;
  }

  // Redirect the App tab
  if (appTabId) {
    const redirectUrl = guideId 
      ? `http://localhost:3001/?guideId=${guideId}` 
      : `http://localhost:3001/`;
      
    chrome.tabs.update(appTabId, { url: redirectUrl, active: true }, function() {
      if (chrome.runtime.lastError) {
        // App tab was closed, open a new one
        chrome.tabs.create({ url: redirectUrl });
      }
    });
  } else {
    // Open a new tab
    const redirectUrl = guideId 
      ? `http://localhost:3001/?guideId=${guideId}` 
      : `http://localhost:3001/`;
    chrome.tabs.create({ url: redirectUrl });
  }
}
