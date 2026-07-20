(function() {
  // 1. Handshake with the React app
  if (window.location.origin === "http://localhost:3001" || window.location.hostname === "localhost") {
    // Listen for pings from React app
    window.addEventListener("ScribExtensionPing", function() {
      console.log('Scrib extension ping received. Sending ready event.');
      window.dispatchEvent(new CustomEvent('ScribeExtensionReady'));
    });

    // Also dispatch ready event immediately in case the page is already loaded and listening
    window.dispatchEvent(new CustomEvent('ScribeExtensionReady'));

    // Listen for messages from React app page to start recording
    window.addEventListener("message", function(event) {
      if (event.data && event.data.type === "SCRIBE_START_RECORDING") {
        console.log("Starting capture for target URL:", event.data.url);
        chrome.runtime.sendMessage({
          type: "START_RECORDING_SESSION",
          url: event.data.url
        });
      }
    });
  }

  // 2. Query recording status from background script
  chrome.runtime.sendMessage({ type: "CHECK_RECORDING_STATUS" }, function(response) {
    if (response && response.isRecording) {
      initializeRecorderUI();
    }
  });

  // Listen for messages from background script (e.g. to start recording UI dynamically)
  chrome.runtime.onMessage.addListener(function(request, sender, sendResponse) {
    if (request.type === "RECORDING_STARTED") {
      initializeRecorderUI();
    } else if (request.type === "RECORDING_STOPPED") {
      removeRecorderUI();
    }
  });

  let shadowRoot = null;
  let clickListener = null;
  let inputListener = null;

  function initializeRecorderUI() {
    if (document.getElementById("scrib-recorder-widget-root")) return;

    // Create shadow DOM container for isolated styling
    const root = document.createElement("div");
    root.id = "scrib-recorder-widget-root";
    root.style.position = "fixed";
    root.style.bottom = "20px";
    root.style.left = "20px";
    root.style.zIndex = "2147483647"; // Max z-index
    root.style.pointerEvents = "none";
    document.body.appendChild(root);

    shadowRoot = root.attachShadow({ mode: "open" });

    // Styles for the widget
    const style = document.createElement("style");
    style.textContent = `
      .widget-container {
        pointer-events: auto;
        background: rgba(18, 18, 28, 0.85);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.12);
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5), 0 0 1px rgba(255, 255, 255, 0.2) inset;
        border-radius: 16px;
        padding: 12px 20px;
        display: flex;
        align-items: center;
        gap: 16px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        color: #ffffff;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      }
      .recording-info {
        display: flex;
        align-items: center;
        gap: 10px;
      }
      .pulse-dot {
        width: 10px;
        height: 10px;
        background-color: #ff4b4b;
        border-radius: 50%;
        box-shadow: 0 0 0 0 rgba(255, 75, 75, 0.7);
        animation: pulse 1.6s infinite;
      }
      .recording-text {
        font-size: 13px;
        font-weight: 600;
        letter-spacing: 0.5px;
      }
      .controls {
        display: flex;
        align-items: center;
        gap: 8px;
        border-left: 1px solid rgba(255, 255, 255, 0.15);
        padding-left: 16px;
      }
      .btn {
        width: 32px;
        height: 32px;
        border-radius: 50%;
        border: none;
        cursor: pointer;
        display: flex;
        align-items: center;
        justifyContent: center;
        color: white;
        transition: all 0.2s ease;
        padding: 0;
      }
      .btn-complete {
        background: linear-gradient(135deg, #10b981 0%, #059669 100%);
        box-shadow: 0 2px 8px rgba(16, 185, 129, 0.3);
      }
      .btn-complete:hover {
        transform: scale(1.08);
        box-shadow: 0 4px 12px rgba(16, 185, 129, 0.5);
      }
      .btn-cancel {
        background: rgba(255, 255, 255, 0.08);
        border: 1px solid rgba(255, 255, 255, 0.15);
      }
      .btn-cancel:hover {
        background: rgba(239, 68, 68, 0.15);
        border-color: rgba(239, 68, 68, 0.5);
        transform: scale(1.05);
      }
      .icon {
        width: 16px;
        height: 16px;
        fill: currentColor;
      }
      @keyframes pulse {
        0% {
          transform: scale(0.95);
          box-shadow: 0 0 0 0 rgba(255, 75, 75, 0.7);
        }
        70% {
          transform: scale(1);
          box-shadow: 0 0 0 8px rgba(255, 75, 75, 0);
        }
        100% {
          transform: scale(0.95);
          box-shadow: 0 0 0 0 rgba(255, 75, 75, 0);
        }
      }
    `;

    // Widget HTML Structure
    const container = document.createElement("div");
    container.className = "widget-container";
    container.innerHTML = `
      <div class="recording-info">
        <div class="pulse-dot"></div>
        <div class="recording-text">SCRIB RECORDING</div>
      </div>
      <div class="controls">
        <button id="btnComplete" class="btn btn-complete" title="Done Recording">
          <svg class="icon" viewBox="0 0 20 20"><path d="M0 11l2-2 5 5L18 3l2 2L7 18z"/></svg>
        </button>
        <button id="btnCancel" class="btn btn-cancel" title="Cancel Recording">
          <svg class="icon" viewBox="0 0 20 20"><path d="M10 8.586L2.929 1.515 1.515 2.929 8.586 10l-7.071 7.071 1.414 1.414L10 11.414l7.071 7.071 1.414-1.414L11.414 10l7.071-7.071-1.414-1.414L10 8.586z"/></svg>
        </button>
      </div>
    `;

    shadowRoot.appendChild(style);
    shadowRoot.appendChild(container);

    // Button event listeners
    shadowRoot.getElementById("btnComplete").addEventListener("click", function() {
      chrome.runtime.sendMessage({ type: "STOP_RECORDING_SESSION", save: true });
    });
    shadowRoot.getElementById("btnCancel").addEventListener("click", function() {
      chrome.runtime.sendMessage({ type: "STOP_RECORDING_SESSION", save: false });
    });

    // Start event listeners for user actions
    startCaptureListeners();
  }

  function removeRecorderUI() {
    const root = document.getElementById("scrib-recorder-widget-root");
    if (root) {
      root.remove();
    }
    stopCaptureListeners();
  }

  function startCaptureListeners() {
    stopCaptureListeners(); // Ensure no duplicates

    // Click Listener
    clickListener = function(event) {
      // Ignore clicks on our own widget
      const widgetRoot = document.getElementById("scrib-recorder-widget-root");
      if (widgetRoot && widgetRoot.contains(event.target)) return;

      const target = event.target;
      const caption = getElementDescription(target);

      // Coordinate percentages relative to viewport size
      const clickXPercent = (event.clientX / window.innerWidth) * 100;
      const clickYPercent = (event.clientY / window.innerHeight) * 100;

      // Send to background script
      chrome.runtime.sendMessage({
        type: "CAPTURE_STEP",
        caption: caption,
        x: clickXPercent,
        y: clickYPercent
      });
    };

    // Text Input Blur Listener (to catch text typing)
    inputListener = function(event) {
      const target = event.target;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") {
        // Only record if value is not empty
        if (target.value && target.value.trim().length > 0) {
          const name = target.placeholder || target.name || target.id || "input field";
          // Mask sensitive input like password
          const value = target.type === "password" ? "********" : target.value;
          const caption = `Type "${value}" in the "${name}" field`;
          
          // Capture coordinates and size of the input box relative to the viewport
          const rect = target.getBoundingClientRect();
          const leftPercent = (rect.left / window.innerWidth) * 100;
          const topPercent = (rect.top / window.innerHeight) * 100;
          const widthPercent = (rect.width / window.innerWidth) * 100;
          const heightPercent = (rect.height / window.innerHeight) * 100;

          chrome.runtime.sendMessage({
            type: "CAPTURE_STEP",
            caption: caption,
            x: leftPercent,
            y: topPercent,
            width: widthPercent,
            height: heightPercent,
            is_typing: true
          });
        }
      }
    };

    document.addEventListener("click", clickListener, true);
    document.addEventListener("blur", inputListener, true);
  }

  function stopCaptureListeners() {
    if (clickListener) {
      document.removeEventListener("click", clickListener, true);
      clickListener = null;
    }
    if (inputListener) {
      document.removeEventListener("blur", inputListener, true);
      inputListener = null;
    }
  }

  function getElementDescription(element) {
    if (!element) return "Click on screen";

    // 1. Check for buttons
    if (element.tagName === "BUTTON" || element.closest("button")) {
      const btn = element.tagName === "BUTTON" ? element : element.closest("button");
      const text = (btn.innerText || btn.value || "").trim();
      return `Click the **${text || "button"}**`;
    }

    // 2. Check for links
    if (element.tagName === "A" || element.closest("a")) {
      const link = element.tagName === "A" ? element : element.closest("a");
      const text = (link.innerText || "").trim();
      return `Click the **${text || "link"}** link`;
    }

    // 3. Check for input fields
    if (element.tagName === "INPUT" || element.tagName === "TEXTAREA" || element.tagName === "SELECT") {
      const name = element.placeholder || element.name || element.id || "input field";
      return `Click on the **${name}** input field`;
    }

    // 4. Default fallback: walk up DOM to find an item with text or use the tag name
    let el = element;
    let text = "";
    let limit = 3; // search up 3 levels maximum
    while (el && text === "" && limit > 0) {
      text = (el.innerText || "").trim();
      el = el.parentElement;
      limit--;
    }

    // Shorten text if it's too long
    if (text.length > 30) {
      text = text.substring(0, 27) + "...";
    }

    const tagName = element.tagName.toLowerCase();
    return `Click on the **${text || tagName}** ${tagName}`;
  }
})();
