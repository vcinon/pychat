/**
 * Entry point: reads connection details from the credentials file (via the
 * `load_credentials` Rust command) and connects straight away -- there is
 * no login form. See src-tauri/src/lib.rs for the file format/location.
 */
import { invoke } from "@tauri-apps/api/core";
import { ChatClient } from "./client";
import { DomUI } from "./ui";

interface StoredCredentials {
  username: string;
  password: string;
  http_url: string;
  ws_url: string;
}

async function bootstrap(): Promise<void> {
  let creds: StoredCredentials;
  try {
    creds = await invoke<StoredCredentials>("load_credentials");
  } catch (err) {
    showFatalError(err instanceof Error ? err.message : String(err));
    return;
  }

  const ui = new DomUI(creds.username);

  // Commands [starts with /]

  function handleCommand(command: string): boolean {
    switch (command.toLowerCase()) {
      case "/clear":
        ui.clearMessages();
        return true;

      default:
        ui.showError(`Unknown command: ${command}`);
        return true;
    }
  }

  function showFatalError(message: string): void {
    document.getElementById("app")!.hidden = true;
    const overlay = document.getElementById("fatal-error") as HTMLDivElement;
    const messageEl = document.getElementById(
      "fatal-error-message",
    ) as HTMLParagraphElement;
    messageEl.textContent = message;
    overlay.hidden = false;
  }

  function setupComposer(client: ChatClient): void {
    const input = document.getElementById("composer-input") as HTMLDivElement;
    const attachBtn = document.getElementById(
      "attach-btn",
    ) as HTMLButtonElement;
    const fileInput = document.getElementById("file-input") as HTMLInputElement;

    const sendCurrentText = (): void => {
      const text = input.innerText.replace(/\n+$/, "");
      if (!text.trim()) return;
      if (text.startsWith("/")) {
        if (handleCommand(text)) {
          input.textContent = "";
          //input.enterKeyHint = "Ok";
          return;
        }
      }
      void client.sendMessage(text);
      input.textContent = "";
    };

    input.addEventListener("keydown", (event: KeyboardEvent) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendCurrentText();
      }
    });

    let typingActive = false;
    input.addEventListener("input", () => {
      const hasText = input.innerText.trim().length > 0;
      if (hasText && !typingActive) {
        typingActive = true;
        client.setTyping(true);
      } else if (!hasText && typingActive) {
        typingActive = false;
        client.setTyping(false);
      }
    });

    attachBtn.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", () => {
      const file = fileInput.files?.[0];
      if (file) void client.sendFile(file);
      fileInput.value = "";
    });

    // Paste an image directly from the clipboard.
    input.addEventListener("paste", (event: ClipboardEvent) => {
      const items = event.clipboardData?.items;
      if (!items) return;
      for (const item of items) {
        if (item.type.startsWith("image/")) {
          event.preventDefault();
          const file = item.getAsFile();
          if (file) void client.sendFile(file);
          return;
        }
      }
    });

    // Drag and drop a file onto the window.
    window.addEventListener("dragover", (event: DragEvent) =>
      event.preventDefault(),
    );
    window.addEventListener("drop", (event: DragEvent) => {
      event.preventDefault();
      const file = event.dataTransfer?.files?.[0];
      if (file) void client.sendFile(file);
    });

    document
      .getElementById("format-help-btn")
      ?.addEventListener("click", () => {
        void client.sendMessage(
          "Formatting help: **bold**, *italic*, ~~strikethrough~~, `inline code`, and ```code blocks```. URLs are linked automatically.",
        );
      });
  }

  function requestNotificationPermission(): void {
    if ("Notification" in window && Notification.permission === "default") {
      void Notification.requestPermission();
    }
  }

  const client = new ChatClient(
    {
      username: creds.username,
      password: creds.password,
      httpUrl: creds.http_url,
      wsUrl: creds.ws_url,
    },
    ui,
  );

  // If the very first connection attempt fails (bad password, unreachable
  // server), surface it clearly instead of leaving the app stuck on
  // "Connecting...". Reconnect attempts after that report through the
  // normal in-app error toast (see ChatClient/DomUI.showError).
  client.onAuthResult = (result) => {
    if (!result.ok) {
      showFatalError(result.reason);
      client.disconnect();
    }
  };

  setupComposer(client);
  requestNotificationPermission();
  window.addEventListener("beforeunload", () => client.disconnect());
  client.connect();
}

document.addEventListener("DOMContentLoaded", () => void bootstrap());
