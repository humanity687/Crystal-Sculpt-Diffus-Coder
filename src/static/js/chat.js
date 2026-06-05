// This file is part of Crystal-Sculpt-Diffus-Coder.
// Crystal-Sculpt-Diffus-Coder is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
// Crystal-Sculpt-Diffus-Coder is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
// You should have received a copy of the GNU Affero General Public License along with Crystal-Sculpt-Diffus-Coder.  If not, see <https://www.gnu.org/licenses/>.

window.katexDisableDollar = true;
const chatMessages = document.getElementById("chat-messages");
const messageInput = document.getElementById("message-input");
const sendBtn = document.getElementById("send-btn");
window.chatMessages = chatMessages;

let currentAbortController = null;
let isGenerating = false;
let currentUserMessage = "";
let currentPartialText = "";
let currentAssistantMsgDiv = null;
let currentKnowledgeItems = [];
let currentKnowledgeBlock = null;
let currentCrystalItems = [];
let currentCrystalBlock = null;
let sessionTotalTokens = 0;

/**
 * Check whether the user is currently scrolled near the bottom of the chat.
 * @returns {boolean}
 */
function isUserAtBottom() {
  const el = window.chatMessages;
  if (!el) return false;
  // Allow a small buffer (10px) so that slight variations don't break the detection
  return el.scrollTop + el.clientHeight >= el.scrollHeight - 10;
}

/**
 * Scroll the chat container to the very bottom immediately.
 */
function scrollToBottom() {
  const el = window.chatMessages;
  if (!el) return;
  el.scrollTo({
    top: el.scrollHeight,
    behavior: "smooth",
  });
}

/**
 * Highlight all unprocessed code blocks inside a container using highlight.js.
 * @param {HTMLElement} container
 */
function highlightCodeBlocks(container) {
  if (!container) return;
  // Select all code blocks that haven't been highlighted yet (no 'hljs' class).
  container.querySelectorAll("pre code:not(.hljs)").forEach((block) => {
    hljs.highlightElement(block);
  });
}

/**
 * Render all unprocessed Mermaid code blocks inside a container as SVG diagrams.
 * @param {HTMLElement} container
 */
async function renderMermaidBlocks(container) {
  if (!container) return;
  const blocks = container.querySelectorAll(
    "pre code.language-mermaid:not(.mermaid-rendered)",
  );
  for (const code of blocks) {
    const pre = code.parentElement;
    const mermaidCode = code.textContent;
    try {
      const id = "mermaid-" + Math.random().toString(36).substr(2, 9);
      const { svg } = await mermaid.render(id, mermaidCode);
      const wrapper = document.createElement("div");
      wrapper.className = "mermaid-wrapper";
      wrapper.innerHTML = svg;
      pre.replaceWith(wrapper);
    } catch (err) {
      console.error("Mermaid render failed:", err);
      pre.innerHTML = `<div class="mermaid-error">Mermaid render error: ${err.message}</div>`;
    }
  }
}

function escapeHtml(str) {
  return str.replace(/[&<>]/g, function (m) {
    if (m === "&") return "&amp;";
    if (m === "<") return "&lt;";
    if (m === ">") return "&gt;";
    return m;
  });
}

function sanitizeForMarkdown(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function wrapTables(container) {
  container.querySelectorAll("table").forEach((table) => {
    if (table.parentElement.classList.contains("table-scroll-wrapper")) return;
    const wrapper = document.createElement("div");
    wrapper.className = "table-scroll-wrapper";
    table.parentNode.insertBefore(wrapper, table);
    wrapper.appendChild(table);
  });
}

/**
 * Full Markdown rendering: marked.parse + tables + code highlight + mermaid + math.
 * Used by both inline confirm blocks and modal overlays.
 * @param {HTMLElement} container
 * @param {string} rawMarkdown
 */
function renderFullMarkdown(container, rawMarkdown) {
  try {
    container.innerHTML = marked.parse(rawMarkdown);
  } catch (e) {
    container.textContent = rawMarkdown;
    return;
  }
  wrapTables(container);
  highlightCodeBlocks(container);
  renderMermaidBlocks(container);
  if (window.renderMathInElement) {
    window.renderMathInElement(container, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "$", right: "$", display: false },
      ],
    });
  }
}

/**
 * Create a modal overlay with backdrop. Returns {overlay, card, close}.
 * @returns {{overlay: HTMLElement, card: HTMLElement, close: () => void}}
 */
function createModalOverlay() {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";

  const card = document.createElement("div");
  card.className = "modal-card";
  overlay.appendChild(card);

  // Click backdrop to close
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) {
      closeModal(overlay);
    }
  });

  // Esc to close
  const onKey = (e) => {
    if (e.key === "Escape") closeModal(overlay);
  };
  document.addEventListener("keydown", onKey);

  const close = () => {
    document.removeEventListener("keydown", onKey);
    closeModal(overlay);
  };

  return { overlay, card, close };
}

function closeModal(overlay) {
  overlay.classList.add("closing");
  setTimeout(() => {
    if (overlay.parentElement) overlay.remove();
  }, 220);
}

function renderStreamingMarkdown(msgDiv, rawText) {
  msgDiv._rawText = rawText;
  let contentContainer = msgDiv.querySelector(
    ".assistant-content:last-of-type",
  );
  if (!contentContainer) {
    contentContainer = document.createElement("div");
    contentContainer.className = "assistant-content";
    msgDiv.appendChild(contentContainer);
  }
  try {
    const html = marked.parse(rawText);
    contentContainer.innerHTML = html;
  } catch (e) {
    contentContainer.textContent = rawText;
  }
  wrapTables(contentContainer);
  // Apply code highlighting to the freshly rendered Markdown
  highlightCodeBlocks(contentContainer);
  renderMermaidBlocks(contentContainer);
  const existingDot = contentContainer.querySelector(".typing-dot");
  if (existingDot) existingDot.remove();
  const dot = document.createElement("span");
  dot.className = "typing-dot";
  const lastChild = contentContainer.lastElementChild;
  if (lastChild) {
    lastChild.appendChild(dot);
  } else {
    contentContainer.appendChild(dot);
  }
}

function updateKnowledgeBlock(msgDiv, knowledgeItems) {
  msgDiv._knowledgeItems = knowledgeItems;
  if (!knowledgeItems.length) {
    if (currentKnowledgeBlock) currentKnowledgeBlock.remove();
    currentKnowledgeBlock = null;
    return;
  }
  // If currentKnowledgeBlock belongs to a different message, reset it
  if (currentKnowledgeBlock && currentKnowledgeBlock.parentElement !== msgDiv) {
    currentKnowledgeBlock = null;
  }
  if (!currentKnowledgeBlock) {
    currentKnowledgeBlock = document.createElement("div");
    currentKnowledgeBlock.className = "assistant-block knowledge-block";
    const header = document.createElement("div");
    header.className = "block-header";
    const icon = document.createElement("span");
    icon.className = "toggle-icon";
    icon.textContent = "▶";
    header.appendChild(icon);
    header.appendChild(
      document.createTextNode(
        t("knowledge.title") + " (" + knowledgeItems.length + ")",
      ),
    );
    const contentDiv = document.createElement("div");
    contentDiv.className = "block-content";
    const inner = document.createElement("div");
    inner.style.display = "flex";
    inner.style.flexDirection = "column";
    inner.style.gap = "0.75rem";
    contentDiv.appendChild(inner);
    currentKnowledgeBlock.appendChild(header);
    currentKnowledgeBlock.appendChild(contentDiv);
    header.addEventListener("click", () => {
      const isOpen = contentDiv.classList.contains("show");
      if (isOpen) {
        contentDiv.classList.remove("show");
        icon.textContent = "▶";
      } else {
        contentDiv.classList.add("show");
        icon.textContent = "▼";
      }
    });
    msgDiv.insertBefore(currentKnowledgeBlock, msgDiv.firstChild);
  }
  const inner = currentKnowledgeBlock.querySelector(".block-content > div");
  inner.innerHTML = "";
  knowledgeItems.forEach((item) => {
    // item is now a structured dict: {text, title, icon, doc_type, memory_id, score}
    const text = typeof item === "string" ? item : (item.text || "");
    const icon = (item && item.icon) || "📄";
    const title = (item && item.title) || "";
    const docType = (item && item.doc_type) || "";
    const memoryId = (item && item.memory_id) || "";
    const score = (item && item.score != null) ? ` · ${(item.score * 100).toFixed(0)}%` : "";

    // Build summary line: icon + title/type + score
    let summaryLabel = "";
    if (title) {
      summaryLabel = `${icon} ${escapeHtml(title)}${score}`;
    } else {
      const short = text.substring(0, 60) + (text.length > 60 ? "…" : "");
      summaryLabel = `${icon} ${escapeHtml(short)}${score}`;
    }
    if (memoryId) {
      summaryLabel += ` <span style="color:#888;font-size:0.65rem;">[${escapeHtml(memoryId)}]</span>`;
    }

    const itemDiv = document.createElement("div");
    itemDiv.className = "knowledge-item";
    const sumDiv = document.createElement("div");
    sumDiv.className = "knowledge-summary";
    sumDiv.innerHTML = `${summaryLabel} <span class="toggle-arrow" style="font-size:0.7rem;">▼</span>`;
    const fullDiv = document.createElement("div");
    fullDiv.className = "knowledge-full";
    try {
      const html = marked.parse(text);
      fullDiv.innerHTML = html;
      wrapTables(fullDiv);
      highlightCodeBlocks(fullDiv);
      renderMermaidBlocks(fullDiv);
      if (window.renderMathInElement) {
        window.renderMathInElement(fullDiv, {
          delimiters: [
            { left: "$$", right: "$$", display: true },
            { left: "$", right: "$", display: false },
          ],
        });
      }
    } catch (e) {
      fullDiv.textContent = text;
    }
    sumDiv.addEventListener("click", (e) => {
      e.stopPropagation();
      fullDiv.classList.toggle("show");
      const iconSpan = sumDiv.querySelector(".toggle-arrow");
      if (iconSpan) {
        iconSpan.textContent = fullDiv.classList.contains("show") ? "▼" : "▶";
      }
    });
    itemDiv.appendChild(sumDiv);
    itemDiv.appendChild(fullDiv);
    inner.appendChild(itemDiv);
  });
  const header = currentKnowledgeBlock.querySelector(".block-header");
  header.lastChild.textContent =
    t("knowledge.title") + " (" + knowledgeItems.length + ")";
}

function updateCrystalBlock(msgDiv, crystalItems) {
  msgDiv._crystalItems = crystalItems;
  if (!crystalItems.length) {
    if (currentCrystalBlock) currentCrystalBlock.remove();
    currentCrystalBlock = null;
    return;
  }
  if (currentCrystalBlock && currentCrystalBlock.parentElement !== msgDiv) {
    currentCrystalBlock = null;
  }
  if (!currentCrystalBlock) {
    currentCrystalBlock = document.createElement("div");
    currentCrystalBlock.className = "assistant-block crystal-block";
    const header = document.createElement("div");
    header.className = "block-header";
    const icon = document.createElement("span");
    icon.className = "toggle-icon";
    icon.textContent = "▶";
    header.appendChild(icon);
    header.appendChild(
      document.createTextNode(
        "🧠 " + t("crystal.title") + " (" + crystalItems.length + ")",
      ),
    );
    const contentDiv = document.createElement("div");
    contentDiv.className = "block-content";
    const inner = document.createElement("div");
    inner.style.display = "flex";
    inner.style.flexDirection = "column";
    inner.style.gap = "0.75rem";
    contentDiv.appendChild(inner);
    currentCrystalBlock.appendChild(header);
    currentCrystalBlock.appendChild(contentDiv);
    header.addEventListener("click", () => {
      const isOpen = contentDiv.classList.contains("show");
      if (isOpen) {
        contentDiv.classList.remove("show");
        icon.textContent = "▶";
      } else {
        contentDiv.classList.add("show");
        icon.textContent = "▼";
      }
    });
    msgDiv.insertBefore(currentCrystalBlock, msgDiv.firstChild);
  }
  const inner = currentCrystalBlock.querySelector(".block-content > div");
  inner.innerHTML = "";
  crystalItems.forEach((item) => {
    const text = typeof item === "string" ? item : (item.text || "");
    const icon = (item && item.icon) || "🧠";
    const title = (item && item.title) || "";
    const docType = (item && item.doc_type) || "";
    const memoryId = (item && item.memory_id) || "";
    const score = (item && item.score != null) ? ` · ${(item.score * 100).toFixed(0)}%` : "";

    let summaryLabel = "";
    if (title) {
      summaryLabel = `${icon} ${escapeHtml(title)}${score}`;
    } else {
      const short = text.substring(0, 60) + (text.length > 60 ? "…" : "");
      summaryLabel = `${icon} ${escapeHtml(short)}${score}`;
    }
    if (memoryId) {
      summaryLabel += ` <span style="color:#888;font-size:0.65rem;">[${escapeHtml(memoryId)}]</span>`;
    }

    const itemDiv = document.createElement("div");
    itemDiv.className = "knowledge-item crystal-item";
    const sumDiv = document.createElement("div");
    sumDiv.className = "knowledge-summary crystal-summary";
    sumDiv.innerHTML = `${summaryLabel} <span class="toggle-arrow" style="font-size:0.7rem;">▼</span>`;
    const fullDiv = document.createElement("div");
    fullDiv.className = "knowledge-full";
    try {
      const html = marked.parse(text);
      fullDiv.innerHTML = html;
      wrapTables(fullDiv);
      highlightCodeBlocks(fullDiv);
      renderMermaidBlocks(fullDiv);
      if (window.renderMathInElement) {
        window.renderMathInElement(fullDiv, {
          delimiters: [
            { left: "$$", right: "$$", display: true },
            { left: "$", right: "$", display: false },
          ],
        });
      }
    } catch (e) {
      fullDiv.textContent = text;
    }
    sumDiv.addEventListener("click", (e) => {
      e.stopPropagation();
      fullDiv.classList.toggle("show");
      const iconSpan = sumDiv.querySelector(".toggle-arrow");
      if (iconSpan) {
        iconSpan.textContent = fullDiv.classList.contains("show") ? "▼" : "▶";
      }
    });
    itemDiv.appendChild(sumDiv);
    itemDiv.appendChild(fullDiv);
    inner.appendChild(itemDiv);
  });
  const header = currentCrystalBlock.querySelector(".block-header");
  header.lastChild.textContent =
    "🧠 " + t("crystal.title") + " (" + crystalItems.length + ")";
}

function addPhaseRollbackBlock(msgDiv, data) {
  const block = document.createElement("div");
  block.className = "assistant-block phase-rollback-block";

  const header = document.createElement("div");
  header.className = "phase-rollback-header";
  header.innerHTML =
    "&#9888;&#65039; " +
    t("chat.phase_rollback_title") +
    " (" +
    data.from +
    " &#8594; " +
    data.to +
    ")";
  block.appendChild(header);

  const body = document.createElement("div");
  body.className = "phase-rollback-body";
  let bodyHtml = "<p>" + t("chat.phase_rollback_desc", { from: data.from, to: data.to }) + "</p>";
  if (data.module) {
    bodyHtml +=
      "<p><strong>" +
      t("chat.module_label") +
      ":</strong> " +
      escapeHtml(data.module) +
      "</p>";
  }
  if (data.contract) {
    bodyHtml += "<p><strong>" + t("chat.rollback_contract") + ":</strong></p>";
    bodyHtml +=
      "<pre class='phase-rollback-contract'>" +
      escapeHtml(data.contract.name || "") +
      "\n" +
      escapeHtml(data.contract.signature || "") +
      "\n\nPre: " +
      escapeHtml(
        Array.isArray(data.contract.preconditions)
          ? data.contract.preconditions.join(", ")
          : data.contract.preconditions || "N/A"
      ) +
      "\nPost: " +
      escapeHtml(
        Array.isArray(data.contract.postconditions)
          ? data.contract.postconditions.join(", ")
          : data.contract.postconditions || "N/A"
      ) +
      "</pre>";
  }
  body.innerHTML = bodyHtml;
  block.appendChild(body);

  // Insert before the first content/typing element
  const firstContent = msgDiv.querySelector(
    ".message-content, .typing-dot, .assistant-block"
  );
  if (firstContent) {
    msgDiv.insertBefore(block, firstContent);
  } else {
    msgDiv.appendChild(block);
  }
}

// ── System Injection Notice (collapsible) ──────────────────────────────────
// Shows when set_project / dependency tools inject system messages.
// Folded by default; click header to expand.
function addSystemInjectionBlock(msgDiv, data) {
  const block = document.createElement("div");
  block.className = "assistant-block system-injection-block";

  // Header: source + kind summary, click to toggle
  const header = document.createElement("div");
  header.className = "block-header injection-header";

  const sourceLabel = data.source === "set_project"
    ? "set_project"
    : data.source === "dependency"
    ? "dependency"
    : data.source;
  const kindLabel = {
    "phase_guidance": "相位指引",
    "crystal_context": "结晶上下文",
    "module_switch": "模块切换",
    "phase_rollback": "相位回退",
    "knowledge_summary": "知识摘要",
  }[data.kind] || data.kind;

  header.innerHTML =
    '<span class="injection-icon">&#128225;</span> ' +
    '<strong>' + (t("chat.system_injection") || "System Injection") + '</strong> ' +
    '<span class="injection-source">[' + escapeHtml(sourceLabel) + ']</span> ' +
    escapeHtml(kindLabel) +
    ' <span class="injection-summary">' + escapeHtml(data.summary || "") + '</span>' +
    ' <span class="injection-toggle">&#9654;</span>';

  // Body: metadata table + injected message content, hidden by default
  const body = document.createElement("div");
  body.className = "injection-body";
  body.style.display = "none";

  let bodyHtml = '<table class="injection-detail-table">';
  if (data.phase) {
    bodyHtml +=
      "<tr><td><strong>Phase</strong></td><td>" +
      escapeHtml(data.phase) + "</td></tr>";
  }
  if (data.module) {
    bodyHtml +=
      "<tr><td><strong>Module</strong></td><td>" +
      escapeHtml(data.module) + "</td></tr>";
  }
  if (data.from_phase) {
    bodyHtml +=
      "<tr><td><strong>From</strong></td><td>" +
      escapeHtml(data.from_phase) + "</td></tr>";
  }
  if (data.to_phase) {
    bodyHtml +=
      "<tr><td><strong>To</strong></td><td>" +
      escapeHtml(data.to_phase) + "</td></tr>";
  }
  if (data.old_module) {
    bodyHtml +=
      "<tr><td><strong>Old Module</strong></td><td>" +
      escapeHtml(data.old_module) + "</td></tr>";
  }
  if (data.new_module) {
    bodyHtml +=
      "<tr><td><strong>New Module</strong></td><td>" +
      escapeHtml(data.new_module) + "</td></tr>";
  }
  bodyHtml += "</table>";

  // Injected message content — always include a pre block
  var previewText = data.preview || "";
  var truncatedNote = "";
  if (previewText.length >= 800) {
    truncatedNote = "\n\n... [truncated at 800 chars]";
  }
  bodyHtml +=
    '<div class="injection-content-label"><strong>Injected Content</strong> ' +
    '(' + previewText.length + ' chars):</div>' +
    '<pre class="injection-content-pre">' +
    escapeHtml(previewText) + truncatedNote +
    '</pre>';
  body.innerHTML = bodyHtml;

  // Toggle on header click
  header.addEventListener("click", function () {
    const isHidden = body.style.display === "none";
    body.style.display = isHidden ? "block" : "none";
    header.querySelector(".injection-toggle").innerHTML = isHidden
      ? "&#9660;"
      : "&#9654;";
  });

  block.appendChild(header);
  block.appendChild(body);

  // Insert at top of message
  const firstContent = msgDiv.querySelector(
    ".message-content, .typing-dot, .assistant-block"
  );
  if (firstContent) {
    msgDiv.insertBefore(block, firstContent);
  } else {
    msgDiv.appendChild(block);
  }
}

// ── Context Compression Notice ─────────────────────────────────────────────
// Shows when the agent compresses old messages to fit context window.
function addCompressionNotice(msgDiv, data) {
  const block = document.createElement("div");
  block.className = "assistant-block compression-notice-block";

  const header = document.createElement("div");
  header.className = "compression-header";

  // Module switch compression — show which modules
  if (data.reason === "module_switch" && data.old_module && data.new_module) {
    header.innerHTML =
      "&#128260; " +
      t("chat.compression_title") +
      " (" +
      t("chat.compression_cut", { count: data.cut_messages || 0 }) +
      ", " +
      t("chat.compression_remaining", { count: data.remaining_messages || 0 }) +
      ")<br><small>" +
      escapeHtml(data.old_module) + " &rarr; " + escapeHtml(data.new_module) +
      "</small>";
  } else {
    header.innerHTML =
      "&#128260; " +
      t("chat.compression_title") +
      " (" +
      t("chat.compression_cut", { count: data.cut_messages || 0 }) +
      ", " +
      t("chat.compression_remaining", { count: data.remaining_messages || 0 }) +
      ")";
  }
  block.appendChild(header);

  const body = document.createElement("div");
  body.className = "compression-body";
  body.innerHTML =
    "<p>" +
    t("chat.compression_desc", {
      cut: data.cut_messages || 0,
      remaining: data.remaining_messages || 0,
    }) +
    "</p>" +
    "<p>" +
    t("chat.compression_hint") +
    "</p>";
  block.appendChild(body);

  // Insert at top of message
  const firstContent = msgDiv.querySelector(
    ".message-content, .typing-dot, .assistant-block"
  );
  if (firstContent) {
    msgDiv.insertBefore(block, firstContent);
  } else {
    msgDiv.appendChild(block);
  }
}

// ── Project Status Pill (inline in header) ──────────────────────────────────
// Updates the compact header pill when set_project activates/deactivates.
function updateProjectStatusBar(data) {
  const pill = document.getElementById("project-pill");
  if (!pill) return;

  if (data.active) {
    pill.style.display = "inline-flex";
    pill.classList.remove("inactive");
    pill.classList.add("active");
    pill.querySelector(".pill-phase").textContent = data.phase || "?";
    const modEl = pill.querySelector(".pill-module");
    if (data.module) {
      modEl.style.display = "";
      modEl.textContent = "/" + data.module;
    } else {
      modEl.style.display = "none";
    }
    pill.querySelector(".pill-project").textContent = data.project_id ? " · " + data.project_id : "";
    const reviewBtnGroup = document.getElementById("review-btn-group");
    if (reviewBtnGroup) reviewBtnGroup.style.display = "flex";
  } else {
    pill.style.display = "inline-flex";
    pill.classList.remove("active");
    pill.classList.add("inactive");
    pill.querySelector(".pill-phase").textContent = "";
    pill.querySelector(".pill-module").textContent = "";
    pill.querySelector(".pill-project").textContent = t("chat.project_inactive") || "No project";
    const reviewBtnGroup = document.getElementById("review-btn-group");
    if (reviewBtnGroup) reviewBtnGroup.style.display = "none";
  }
}

// ── Token Usage Bar (top of chat-messages) ──────────────────────────────────
function updateTokenUsageBar(data) {
  const bar = document.getElementById("token-usage-bar");
  const text = document.getElementById("token-usage-text");
  if (!bar || !text) return;

  sessionTotalTokens += data.total_tokens || 0;
  bar.style.display = "flex";

  const fmt = (n) => {
    if (n >= 10000) return (n / 1000).toFixed(1) + "k";
    if (n >= 1000) return (n / 1000).toFixed(1) + "k";
    return String(n);
  };

  text.innerHTML =
    '<span class="token-stat">' +
    '<span class="token-label">本轮</span>' +
    '<span class="token-value">' + fmt(data.total_tokens) + '</span>' +
    '</span>' +
    '<span class="token-sep">|</span>' +
    '<span class="token-stat">' +
    '<span class="token-label">输入</span>' +
    '<span class="token-value">' + fmt(data.input_tokens) + '</span>' +
    '</span>' +
    '<span class="token-sep">|</span>' +
    '<span class="token-stat">' +
    '<span class="token-label">输出</span>' +
    '<span class="token-value">' + fmt(data.output_tokens) + '</span>' +
    '</span>' +
    '<span class="token-sep">|</span>' +
    '<span class="token-stat">' +
    '<span class="token-label">会话</span>' +
    '<span class="token-value">' + fmt(sessionTotalTokens) + '</span>' +
    '</span>';
}

function appendTokenBadge(msgDiv, data) {
  if (!msgDiv) return;
  // Remove existing badge if present
  const existing = msgDiv.querySelector(".token-badge");
  if (existing) existing.remove();
  const badge = document.createElement("span");
  badge.className = "token-badge";
  const fmt = (n) => {
    if (n >= 10000) return (n / 1000).toFixed(1) + "k";
    if (n >= 1000) return (n / 1000).toFixed(1) + "k";
    return String(n);
  };
  badge.textContent = "🔤 " + fmt(data.total_tokens) + " tokens";
  msgDiv.appendChild(badge);
}

function addToolCallBlockStructured(
  msgDiv,
  callId,
  toolName,
  argumentsObj,
  resultText,
) {
  let params = argumentsObj || {};
  if (typeof params !== "object") params = {};
  if (typeof toolName !== "string") {
    toolName = String(toolName);
  }
  const blockDiv = document.createElement("div");
  blockDiv.className = "assistant-block tool-call-block";
  blockDiv.dataset.callId = callId;
  const header = document.createElement("div");
  header.className = "block-header";
  header.dataset.toolName = toolName;
  const icon = document.createElement("span");
  icon.className = "toggle-icon";
  icon.textContent = "▶";
  header.appendChild(icon);
  header.appendChild(
    document.createTextNode(t("tool.using", { name: toolName })),
  );
  const paramsDiv = document.createElement("div");
  paramsDiv.className = "tool-params";
  if (Object.keys(params).length > 0) {
    for (const [key, value] of Object.entries(params)) {
      const paramLine = document.createElement("div");
      paramLine.className = "tool-param";
      let valStr =
        typeof value === "object"
          ? JSON.stringify(value, null, 2)
          : String(value);
      paramLine.textContent = `${key}: ${valStr}`;
      paramsDiv.appendChild(paramLine);
    }
  } else {
    const fallback = document.createElement("div");
    fallback.className = "tool-param";
    fallback.textContent = t("tool.no_params");
    paramsDiv.appendChild(fallback);
  }
  const resultLabel = document.createElement("div");
  resultLabel.className = "tool-param";
  resultLabel.style.fontWeight = "bold";
  resultLabel.style.marginTop = "0.5rem";
  resultLabel.textContent = t("tool.result");
  paramsDiv.appendChild(resultLabel);
  const resultContent = document.createElement("div");
  resultContent.className = "tool-param";
  resultContent.style.padding = "0.25rem 0";
  if (resultText && resultText !== "null" && resultText !== "") {
    resultContent.textContent = resultText;
    header.lastChild.textContent = t("tool.used", { name: toolName });
  } else {
    resultContent.textContent = t("tool.executing");
    resultContent.classList.add("tool-result-pending");
  }
  paramsDiv.appendChild(resultContent);
  blockDiv.appendChild(header);
  blockDiv.appendChild(paramsDiv);
  header.addEventListener("click", () => {
    const isOpen = paramsDiv.classList.contains("show");
    if (isOpen) {
      paramsDiv.classList.remove("show");
      icon.textContent = "▶";
    } else {
      paramsDiv.classList.add("show");
      icon.textContent = "▼";
    }
  });
  msgDiv.appendChild(blockDiv);
  return blockDiv;
}

function updateToolCallResult(msgDiv, callId, resultText) {
  const blockDiv = msgDiv.querySelector(
    `.tool-call-block[data-call-id="${callId}"]`,
  );
  if (!blockDiv) return;
  const header = blockDiv.querySelector(".block-header");
  if (header) {
    const toolName = header.dataset.toolName;
    header.lastChild.textContent = t("tool.used", { name: toolName });
  }
  const pendingResult = blockDiv.querySelector(".tool-result-pending");
  if (pendingResult) {
    pendingResult.textContent = resultText;
    pendingResult.classList.remove("tool-result-pending");
  } else {
    const allParams = blockDiv.querySelectorAll(".tool-param");
    const lastParam = allParams[allParams.length - 1];
    if (lastParam) lastParam.textContent = resultText;
  }
}

function addConfirmationBlock(msgDiv, confirmId, toolName, argumentsObj, warning) {
  let params = argumentsObj || {};
  if (typeof params !== "object") params = {};
  const blockDiv = document.createElement("div");
  blockDiv.className = "confirm-block";
  blockDiv.dataset.confirmId = confirmId;
  const header = document.createElement("div");
  header.className = "confirm-header";
  header.textContent = t("tool.confirm", { name: toolName });
  blockDiv.appendChild(header);

  // Show danger warning banner if present
  if (warning) {
    const warningDiv = document.createElement("div");
    warningDiv.className = "confirm-warning";
    warningDiv.textContent = typeof t !== "undefined" && t("tool.command_warning")
      ? t("tool.command_warning")
      : warning;
    blockDiv.appendChild(warningDiv);
  }

  const paramsDiv = document.createElement("div");
  paramsDiv.className = "confirm-params";
  let displayParams = "";
  if (toolName === "write") {
    const path = params.path || "";
    const mode = params.mode || "overwrite";
    const content = params.content || "";
    const startLine = params.start_line || 0;
    const endLine = params.end_line || 0;
    displayParams = t("tool.confirm_write_template", {
      path,
      mode,
      content,
      startLine,
      endLine,
    });
  } else if (toolName === "command") {
    const command = params.command || "";
    displayParams = t("tool.confirm_command_template", { command });
  } else {
    displayParams = JSON.stringify(params, null, 2);
  }
  paramsDiv.className = "confirm-params";
  renderFullMarkdown(paramsDiv, displayParams);
  blockDiv.appendChild(paramsDiv);
  const buttonsDiv = document.createElement("div");
  buttonsDiv.className = "confirm-buttons";
  const approveBtn = document.createElement("button");
  approveBtn.className = "confirm-approve";
  approveBtn.textContent = t("tool.approve");
  const rejectBtn = document.createElement("button");
  rejectBtn.className = "confirm-reject";
  rejectBtn.textContent = t("tool.reject");
  buttonsDiv.appendChild(approveBtn);
  buttonsDiv.appendChild(rejectBtn);
  blockDiv.appendChild(buttonsDiv);
  let confirmed = false;
  approveBtn.addEventListener("click", async () => {
    if (confirmed) return;
    confirmed = true;
    approveBtn.disabled = true;
    rejectBtn.disabled = true;
    try {
      await fetchWithAuth("/api/confirm_tool", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm_id: confirmId, approved: true }),
      });
      blockDiv.remove();
    } catch (err) {
      console.error("Failed to send approval", err);
      approveBtn.disabled = false;
      confirmed = false;
    }
  });
  rejectBtn.addEventListener("click", async () => {
    if (confirmed) return;
    confirmed = true;
    approveBtn.disabled = true;
    rejectBtn.disabled = true;
    try {
      await fetchWithAuth("/api/confirm_tool", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm_id: confirmId, approved: false }),
      });
      blockDiv.innerHTML = `<div class="confirm-header">${t("tool.rejected")}</div>`;
    } catch (err) {
      console.error("Failed to send rejection", err);
      approveBtn.disabled = false;
      rejectBtn.disabled = false;
      confirmed = false;
    }
  });
  msgDiv.appendChild(blockDiv);
  return blockDiv;
}

function saveMessagesToLocalStorage() {
  const messages = [];
  document.querySelectorAll(".message").forEach((msgDiv) => {
    const role = msgDiv.classList.contains("user") ? "user" : "assistant";
    if (!msgDiv.classList.contains("temp")) {
      const msg = { role };
      if (role === "assistant") {
        if (msgDiv._rawText) {
          msg.content = msgDiv._rawText;
        } else if (msgDiv._textNode) {
          msg.content = msgDiv._textNode.textContent;
        } else {
          msg.content = msgDiv.textContent;
        }
        if (msgDiv._knowledgeItems && msgDiv._knowledgeItems.length > 0) {
          msg.knowledge = msgDiv._knowledgeItems;
        }
      } else {
        msg.content = msgDiv.textContent;
      }
      messages.push(msg);
    }
  });
  localStorage.setItem("chatMessages", JSON.stringify(messages));
}

function loadMessagesFromLocalStorage() {
  const stored = localStorage.getItem("chatMessages");
  if (stored) {
    const messages = JSON.parse(stored);
    messages.forEach((msg) => {
      const msgDiv = addMessage(msg.role, msg.content, false, "", true);
      if (
        msg.role === "assistant" &&
        msg.knowledge &&
        msg.knowledge.length > 0
      ) {
        msgDiv._knowledgeItems = msg.knowledge;
        updateKnowledgeBlock(msgDiv, msg.knowledge);
      }
    });
    window.chatMessages.scrollTop = window.chatMessages.scrollHeight;
  }
}

function addMessage(
  role,
  content,
  temporary = false,
  extraClass = "",
  parseMarkdown = false,
) {
  const msgDiv = document.createElement("div");
  msgDiv.className = `message ${role} ${extraClass}`;
  if (temporary) msgDiv.classList.add("temp");
  if (role === "assistant" && temporary) {
    msgDiv._rawText = "";
    const contentContainer = document.createElement("div");
    contentContainer.className = "assistant-content";
    msgDiv.appendChild(contentContainer);
    renderStreamingMarkdown(msgDiv, content);
  } else if (parseMarkdown && !temporary) {
    if (role === "user") {
      const safeContent = sanitizeForMarkdown(content);
      const html = marked.parse(safeContent);
      msgDiv.innerHTML = html;
    } else {
      const html = marked.parse(content);
      msgDiv.innerHTML = html;
    }
    wrapTables(msgDiv);
    // Highlight code blocks in the fully rendered message
    highlightCodeBlocks(msgDiv);
    renderMermaidBlocks(msgDiv);
    if (window.renderMathInElement) {
      window.renderMathInElement(msgDiv, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "$", right: "$", display: false },
        ],
      });
    }
  } else {
    msgDiv.textContent = content;
  }
  chatMessages.appendChild(msgDiv);
  if (!temporary) saveMessagesToLocalStorage();
  return msgDiv;
}

function updateMessage(msgDiv, content) {
  msgDiv._rawText = content;
  const contentContainer = msgDiv.querySelector(".assistant-content");
  if (contentContainer) {
    try {
      const html = marked.parse(content);
      contentContainer.innerHTML = html;
      wrapTables(contentContainer);
      // Highlight freshly rendered code
      highlightCodeBlocks(contentContainer);
      renderMermaidBlocks(contentContainer);
      let dot = contentContainer.querySelector(".typing-dot");
      if (!dot) {
        dot = document.createElement("span");
        dot.className = "typing-dot";
      } else {
        dot.remove();
      }
      const lastChild = contentContainer.lastElementChild;
      if (lastChild) lastChild.appendChild(dot);
      else contentContainer.appendChild(dot);
    } catch (e) {
      contentContainer.textContent = content;
    }
  } else {
    msgDiv.textContent = content;
  }
  msgDiv.classList.remove("temp");
  saveMessagesToLocalStorage();
}

function removeTypingDot(msgDiv) {
  const lastContainer = msgDiv.querySelector(".assistant-content:last-of-type");
  if (lastContainer) {
    const dot = lastContainer.querySelector(".typing-dot");
    if (dot) dot.remove();
  }
}

function setSendButtonToStop() {
  sendBtn.textContent = t("chat.stop");
  sendBtn.removeEventListener("click", sendMessage);
  sendBtn.addEventListener("click", stopGeneration);
}

function setSendButtonToSend() {
  sendBtn.textContent = t("chat.send");
  sendBtn.removeEventListener("click", stopGeneration);
  sendBtn.addEventListener("click", sendMessage);
}

function stopGeneration() {
  if (currentAbortController) {
    currentAbortController.abort();
    currentAbortController = null;
  }
  setSendButtonToSend();
  isGenerating = false;
  if (currentPartialText && currentUserMessage) {
    fetchWithAuth("/api/save_partial", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_message: currentUserMessage,
        partial_response: currentPartialText,
      }),
    }).catch((e) => console.error("Failed to save partial response", e));
    if (currentAssistantMsgDiv) {
      const stopText = currentPartialText + "\n\n" + t("chat.stopped");
      currentAssistantMsgDiv._rawText = stopText;
      const contentContainer =
        currentAssistantMsgDiv.querySelector(".assistant-content");
      if (contentContainer) {
        try {
          contentContainer.innerHTML = marked.parse(stopText);
          wrapTables(contentContainer);
          // Highlight code blocks when user stops generation
          highlightCodeBlocks(contentContainer);
          renderMermaidBlocks(contentContainer);
        } catch (e) {
          contentContainer.textContent = stopText;
        }
      }
      removeTypingDot(currentAssistantMsgDiv);
      currentAssistantMsgDiv.classList.remove("temp");
      saveMessagesToLocalStorage();
    } else {
      addMessage("assistant", currentPartialText + "\n\n" + t("chat.stopped"));
    }
  } else {
    addMessage("assistant", t("chat.stopped"));
  }
  currentUserMessage = "";
  currentPartialText = "";
  currentAssistantMsgDiv = null;
  currentKnowledgeItems = [];
  currentKnowledgeBlock = null;
  currentCrystalItems = [];
  currentCrystalBlock = null;
  // Clean up any orphaned modal overlay
  const orphanModal = document.querySelector(".modal-overlay");
  if (orphanModal) {
    orphanModal.classList.add("closing");
    setTimeout(() => { if (orphanModal.parentElement) orphanModal.remove(); }, 220);
  }
  // Clean up any orphaned write proposal panel
  const orphanPanel = document.querySelector(".code-review-panel-wrapper");
  if (orphanPanel) {
    orphanPanel.classList.add("closing");
    setTimeout(() => orphanPanel.remove(), 250);
    document.getElementById("chat-page").classList.remove("split-layout");
  }
  const orphanHandle = document.querySelector(".split-resize-handle");
  if (orphanHandle) orphanHandle.remove();
  // Reset input area right offset from panel layout
  const chatInput = document.querySelector(".chat-input-area");
  if (chatInput) chatInput.style.right = "";
}

async function sendMessage() {
  currentKnowledgeItems = [];
  if (currentKnowledgeBlock) {
    currentKnowledgeBlock.remove();
    currentKnowledgeBlock = null;
  }
  currentCrystalItems = [];
  if (currentCrystalBlock) {
    currentCrystalBlock.remove();
    currentCrystalBlock = null;
  }
  const message = messageInput.value.trim();
  if (!message || isGenerating) return;
  isGenerating = true;
  messageInput.value = "";
  currentUserMessage = message;
  currentPartialText = "";
  currentAbortController = new AbortController();
  const signal = currentAbortController.signal;
  setSendButtonToStop();
  addMessage("user", message, false, "", true);
  scrollToBottom();
  const assistantMsgDiv = addMessage(
    "assistant",
    t("chat.thinking"),
    true,
    "",
    false,
  );
  currentAssistantMsgDiv = assistantMsgDiv;
  let fullText = "";
  let receivedHtml = false;
  try {
    const resp = await fetchWithAuth("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
      signal,
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let partialLine = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      // Reassemble lines split across TCP chunks
      const lines = (partialLine + chunk).split("\n");
      partialLine = chunk.endsWith("\n") ? "" : lines.pop();
      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.substring(6));
            if (data.type === "content") {
              fullText += data.text;
              currentPartialText = fullText;
              renderStreamingMarkdown(assistantMsgDiv, fullText);
              assistantMsgDiv.classList.remove("temp");
              // Smart scroll: only auto-scroll when the user is at the bottom
              if (isUserAtBottom()) {
                scrollToBottom();
              }
            } else if (data.type === "tool_call") {
              removeTypingDot(assistantMsgDiv);
              assistantMsgDiv.classList.remove("temp");
              // Clear the initial "thinking" placeholder from old containers
              assistantMsgDiv.querySelectorAll(".assistant-content").forEach(c => {
                if (!c.textContent.trim() || c.textContent.trim() === t("chat.thinking")) {
                  c.textContent = "";
                }
              });
              addToolCallBlockStructured(
                assistantMsgDiv,
                data.call_id,
                data.tool_name,
                data.arguments,
                data.result,
              );
              const newContainer = document.createElement("div");
              newContainer.className = "assistant-content";
              assistantMsgDiv.appendChild(newContainer);
              fullText = "";
            } else if (data.type === "tool_result") {
              updateToolCallResult(assistantMsgDiv, data.call_id, data.result);
            } else if (data.type === "html") {
              receivedHtml = true;
              removeTypingDot(assistantMsgDiv);
              assistantMsgDiv.classList.remove("temp");
              if (window.renderMathInElement) {
                window.renderMathInElement(assistantMsgDiv, {
                  delimiters: [
                    { left: "$$", right: "$$", display: true },
                    { left: "$", right: "$", display: false },
                  ],
                });
              }
              saveMessagesToLocalStorage();
            } else if (data.type === "knowledge") {
              currentKnowledgeItems.push(data);
              updateKnowledgeBlock(assistantMsgDiv, currentKnowledgeItems);
            } else if (data.type === "crystal") {
              currentCrystalItems.push(data);
              updateCrystalBlock(assistantMsgDiv, currentCrystalItems);
            } else if (data.type === "phase_rollback") {
              addPhaseRollbackBlock(assistantMsgDiv, data);
            } else if (data.type === "system_injection") {
              addSystemInjectionBlock(assistantMsgDiv, data);
            } else if (data.type === "compression") {
              addCompressionNotice(assistantMsgDiv, data);
            } else if (data.type === "confirmation_required") {
              addConfirmationBlock(
                assistantMsgDiv,
                data.confirm_id,
                data.tool_name,
                data.arguments,
                data.warning || "",
              );
            } else if (data.type === "write_proposal") {
              await handleWriteProposal(assistantMsgDiv, data);
            } else if (data.type === "approval_required") {
              handleApprovalRequired(assistantMsgDiv, data);
            } else if (data.type === "error") {
              updateMessage(
                assistantMsgDiv,
                t("chat.error", { message: data.text }),
              );
              removeTypingDot(assistantMsgDiv);
            } else if (data.type === "context_restart") {
              // Loop restart: finalize current bubble and start a new one
              removeTypingDot(assistantMsgDiv);
              assistantMsgDiv.classList.remove("temp");
              // Create a fresh assistant bubble for the new context
              assistantMsgDiv = addMessage(
                "assistant",
                t("chat.thinking"),
                true,
                "",
                false,
              );
              currentAssistantMsgDiv = assistantMsgDiv;
              fullText = "";
            } else if (data.type === "project_state") {
              updateProjectStatusBar(data);
            } else if (data.type === "token_usage") {
              updateTokenUsageBar(data);
              appendTokenBadge(assistantMsgDiv, data);
            } else if (data.type === "done") {
              // Stream complete — the HTTP stream will close after this event
            }
          } catch (e) {
            console.error(e);
          }
        }
      }
    }
    if (assistantMsgDiv.querySelector(".typing-dot")) {
      removeTypingDot(assistantMsgDiv);
      saveMessagesToLocalStorage();
    }
  } catch (err) {
    if (err.name !== "AbortError") {
      updateMessage(
        assistantMsgDiv,
        t("chat.network_error", { message: err.message }),
      );
      removeTypingDot(assistantMsgDiv);
    }
  } finally {
    setSendButtonToSend();
    isGenerating = false;
    currentAbortController = null;
    currentUserMessage = "";
    currentPartialText = "";
    currentAssistantMsgDiv = null;
    currentKnowledgeItems = [];
    currentKnowledgeBlock = null;
    currentCrystalItems = [];
    currentCrystalBlock = null;
  }
}

messageInput.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.key === "Enter") sendMessage();
});

// Manual context compression button
const compressBtn = document.getElementById("compress-btn");
if (compressBtn) {
  compressBtn.addEventListener("click", async () => {
    if (isGenerating) return;
    compressBtn.disabled = true;
    try {
      const resp = await fetchWithAuth("/api/compress", { method: "POST" });
      const data = await resp.json();
      if (data.success && data.cut_messages > 0) {
        const msg = t("chat.compress_done", {
          cut: data.cut_messages,
          remaining: data.remaining_messages,
        });
        addMessage("system", msg, false, "compression-notice", true);
        scrollToBottom();
      } else if (data.success) {
        addMessage("system", t("chat.compress_nothing"), false, "compression-notice", true);
        scrollToBottom();
      } else {
        addMessage("system", "Compression failed: " + (data.error || "unknown"), false, "compression-notice", true);
        scrollToBottom();
      }
    } catch (e) {
      addMessage("system", "Compression failed: " + e.message, false, "compression-notice", true);
      scrollToBottom();
    } finally {
      compressBtn.disabled = false;
    }
  });
}

// Automatic code highlighting
(function () {
  const chat = document.getElementById("chat-messages");
  if (!chat) return;

  // Watch for new nodes added to the chat area
  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      mutation.addedNodes.forEach((node) => {
        // Only process element nodes
        if (node.nodeType === Node.ELEMENT_NODE) {
          node.querySelectorAll("pre code:not(.hljs)").forEach((block) => {
            // Ensure a language class exists, otherwise treat as plain text
            if (!block.className.includes("language-")) {
              block.classList.add("language-text");
            }
            hljs.highlightElement(block);
          });
        }
      });
    });
  });

  observer.observe(chat, { childList: true, subtree: true });

  // Also highlight any code blocks already present on page load
  chat.querySelectorAll("pre code:not(.hljs)").forEach((block) => {
    if (!block.className.includes("language-")) {
      block.classList.add("language-text");
    }
    hljs.highlightElement(block);
  });
})();

/**
 * Handle a write_proposal SSE event: fetch the original file, create the
 * code review panel in split-layout mode, and wire up approve/reject.
 * @param {HTMLElement} msgDiv - The assistant message element
 * @param {Object} data - The write_proposal event data
 */
async function handleWriteProposal(msgDiv, data) {
  const confirmId = data.confirm_id;
  const aiContent = data.content || "";

  let args = data.arguments || {};

  const path = args.path || "";
  console.log("Write proposal for path:", path);

  // Fetch original file content
  let originalText = "";
  try {
    const resp = await fetchWithAuth("/api/read_file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    const result = await resp.json();
    originalText = result.content || "";
  } catch (e) {
    console.error("Failed to read original file:", e);
  }

  // Determine language from file extension
  const ext = (path.split(".").pop() || "").toLowerCase();
  const langMap = {
    py: "python",
    js: "javascript",
    ts: "typescript",
    jsx: "javascript",
    tsx: "typescript",
    cpp: "cpp",
    cc: "cpp",
    cxx: "cpp",
    c: "cpp",
    h: "cpp",
    hpp: "cpp",
    java: "java",
    rs: "rust",
    go: "go",
    html: "html",
    htm: "html",
    css: "css",
    json: "json",
    md: "markdown",
    sql: "sql",
  };
  const language = langMap[ext] || "text";

  // Switch to split layout (40/60)
  const chatPage = document.getElementById("chat-page");
  // Clean up any stale modal overlay
  const existingModal = document.querySelector(".modal-overlay");
  if (existingModal) {
    existingModal.classList.add("closing");
    setTimeout(() => { if (existingModal.parentElement) existingModal.remove(); }, 220);
  }
  // Remove any existing side panel (dedup)
  const existingWrapper = chatPage.querySelector(".code-review-panel-wrapper");
  if (existingWrapper) {
    existingWrapper.classList.add("closing");
    setTimeout(() => existingWrapper.remove(), 250);
  }
  // Remove stale resize handle
  const existingHandle = chatPage.querySelector(".split-resize-handle");
  if (existingHandle) existingHandle.remove();
  chatPage.classList.add("split-layout");

  // Resize handle between chat and panel
  const resizeHandle = document.createElement("div");
  resizeHandle.className = "split-resize-handle";
  chatPage.appendChild(resizeHandle);

  // Create wrapper for the panel
  const wrapper = document.createElement("div");
  wrapper.className = "code-review-panel-wrapper";
  chatPage.appendChild(wrapper);

  // ── Resize logic ──
  let resizeStartX = 0;
  let resizeStartWidth = 0;
  const chatInput = document.querySelector(".chat-input-area");

  resizeHandle.addEventListener("mousedown", (e) => {
    e.preventDefault();
    resizeStartX = e.clientX;
    resizeStartWidth = wrapper.offsetWidth;
    resizeHandle.classList.add("active");
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const onMove = (ev) => {
      const dx = resizeStartX - ev.clientX;
      const newPanelWidth = Math.max(300, Math.min(window.innerWidth * 0.6, resizeStartWidth + dx));
      wrapper.style.flex = "0 0 " + newPanelWidth + "px";
      wrapper.style.minWidth = "0";
      wrapper.style.maxWidth = "none";
      if (chatInput) {
        chatInput.style.right = newPanelWidth + "px";
      }
    };
    const onUp = () => {
      resizeHandle.classList.remove("active");
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });

  // Create panel
  const panel = new CodeReviewPanel(
    wrapper,
    path,
    originalText,
    aiContent,
    language,
  );

  panel.onApprove(async (finalContent) => {
    try {
      await fetchWithAuth("/api/write_file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, content: finalContent }),
      });
      await fetchWithAuth("/api/confirm_tool", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          confirm_id: confirmId,
          approved: true,
          final_content: finalContent,
        }),
      });
    } catch (err) {
      console.error("Failed to write/confirm file:", err);
    }
    // Trigger slide-out animation, then clean up
    wrapper.classList.add("closing");
    setTimeout(() => {
      panel.destroy();
      chatPage.classList.remove("split-layout");
      wrapper.remove();
      resizeHandle.remove();
      if (chatInput) chatInput.style.right = "";
    }, 250);
  });

  panel.onReject(async (reason) => {
    try {
      const body = { confirm_id: confirmId, approved: false };
      if (reason) {
        body.rejection_reason = reason;
      }
      await fetchWithAuth("/api/confirm_tool", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch (err) {
      console.error("Failed to reject:", err);
    }
    // Trigger slide-out animation, then clean up
    wrapper.classList.add("closing");
    setTimeout(() => {
      panel.destroy();
      chatPage.classList.remove("split-layout");
      wrapper.remove();
      resizeHandle.remove();
      if (chatInput) chatInput.style.right = "";
    }, 250);
  });
}

/**
 * Handle an approval_required SSE event: render the Lx phase output
 * in a centered modal overlay with full Markdown, attachment previews,
 * and Approve / Reject (with mandatory feedback) buttons.
 * @param {HTMLElement} msgDiv - The assistant message element
 * @param {Object} data - The approval_required event data
 */
function handleApprovalRequired(msgDiv, data) {
  const confirmId = data.confirm_id;
  const phase = data.phase || "";
  const module = data.module || "";
  const content = data.content || "";
  // Normalize files: backend may send a string instead of an array
  let files = data.files || [];
  if (typeof files === "string") {
    try { files = JSON.parse(files); } catch (e) { files = [files]; }
  }
  if (!Array.isArray(files)) files = [];
  const fileContents = data.file_contents || {};

  // Clean up any existing modal
  const existing = document.querySelector(".modal-overlay");
  if (existing) {
    existing.classList.add("closing");
    setTimeout(() => { if (existing.parentElement) existing.remove(); }, 220);
  }

  // Also clean up any stale split-layout state
  const chatPage = document.getElementById("chat-page");
  chatPage.classList.remove("split-layout");
  const existingWrapper = chatPage.querySelector(".approval-panel-wrapper, .code-review-panel-wrapper");
  if (existingWrapper) {
    existingWrapper.classList.add("closing");
    setTimeout(() => existingWrapper.remove(), 250);
  }

  const panel = new ApprovalPanel(phase, module, content, files, fileContents);

  panel.onApprove(async () => {
    try {
      await fetchWithAuth("/api/confirm_tool", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm_id: confirmId, approved: true }),
      });
    } catch (err) {
      console.error("Failed to send approval:", err);
      throw err; // Re-throw so ApprovalPanel re-enables buttons
    }
  });

  panel.onReject(async (rejectionReason) => {
    try {
      const body = { confirm_id: confirmId, approved: false };
      if (rejectionReason) {
        body.rejection_reason = rejectionReason;
      }
      await fetchWithAuth("/api/confirm_tool", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch (err) {
      console.error("Failed to send rejection:", err);
    }
  });
}

/**
 * ApprovalPanel - A centered modal overlay for Lx phase approval.
 * Renders full Markdown (tables, code, mermaid, math), attachment previews,
 * and Approve/Reject buttons. Reject requires mandatory feedback.
 *
 * Uses the modal-overlay system instead of split-layout so the chat stays
 * at full width and the approval content gets a spacious centered card.
 */
class ApprovalPanel {
  /**
   * @param {string} phase
   * @param {string} module
   * @param {string} content - Markdown approval request body
   * @param {string[]} files - Attachment file paths
   * @param {Object} fileContents - Map of file path to content
   */
  constructor(phase, module, content, files, fileContents) {
    this.phase = phase;
    this.module = module;
    this.content = content;
    this.files = files || [];
    this.fileContents = fileContents || {};
    this._approveCallback = null;
    this._rejectCallback = null;
    this._confirmed = false;
    this._init();
  }

  _init() {
    const { overlay, card, close } = createModalOverlay();
    this.overlay = overlay;
    this.card = card;
    this._closeModal = close;

    // ── Header ──
    const header = document.createElement("div");
    header.className = "modal-card-header";

    const left = document.createElement("div");
    left.className = "modal-card-header-left";
    const phaseLabel = this.phase === "L3.1"
      ? "L3.1 — Contract Renegotiation"
      : "Phase " + this.phase;
    left.innerHTML =
      '<span class="phase-badge-sm">' + this._esc(phaseLabel) + '</span>' +
      '<span class="module-label">' + this._esc(this.module) + '</span>';
    header.appendChild(left);

    const closeBtn = document.createElement("button");
    closeBtn.className = "modal-card-close";
    closeBtn.innerHTML = "&#10005;";
    closeBtn.title = "Close (Esc)";
    closeBtn.addEventListener("click", () => {
      // Closing without action = implicit rejection without feedback
      if (!this._confirmed && this._rejectCallback) {
        this._rejectCallback("");
      }
      this._closeModal();
    });
    header.appendChild(closeBtn);
    card.appendChild(header);

    // ── Body: full Markdown rendering ──
    const body = document.createElement("div");
    body.className = "modal-card-body";
    renderFullMarkdown(body, this.content);
    card.appendChild(body);

    // ── Attachments (collapsible) ──
    if (this.files.length > 0) {
      const attachDiv = document.createElement("div");
      attachDiv.className = "modal-card-attachments";

      const toggle = document.createElement("div");
      toggle.className = "modal-card-attachments-toggle";
      toggle.innerHTML = "&#128206; " + this.files.length + " file(s) attached";
      attachDiv.appendChild(toggle);

      const attachBody = document.createElement("div");
      attachBody.className = "modal-card-attachments-body";
      attachBody.style.display = "none";

      for (const fpath of this.files) {
        const fblock = document.createElement("div");
        fblock.className = "modal-attach-file";

        const fname = document.createElement("div");
        fname.className = "modal-attach-name";
        fname.textContent = fpath;
        fblock.appendChild(fname);

        const fcontent = document.createElement("pre");
        fcontent.className = "modal-attach-content";
        const code = document.createElement("code");
        code.textContent = this.fileContents[fpath] || "[Could not read file]";
        fcontent.appendChild(code);
        fblock.appendChild(fcontent);
        attachBody.appendChild(fblock);
      }

      toggle.addEventListener("click", () => {
        const show = attachBody.style.display === "none";
        attachBody.style.display = show ? "block" : "none";
        toggle.innerHTML = (show ? "&#128194;" : "&#128206;") +
          " " + this.files.length + " file(s) " + (show ? "(expanded)" : "(collapsed)");
      });

      attachDiv.appendChild(attachBody);
      card.appendChild(attachDiv);
    }

    // ── Footer: Approve / Reject ──
    const footer = document.createElement("div");
    footer.className = "modal-card-footer";

    this.approveBtn = document.createElement("button");
    this.approveBtn.className = "confirm-approve";
    this.approveBtn.textContent =
      (typeof t !== "undefined" && t("tool.approve")) || "Approve";

    this.rejectBtn = document.createElement("button");
    this.rejectBtn.className = "confirm-reject";
    this.rejectBtn.textContent =
      (typeof t !== "undefined" && t("tool.reject")) || "Reject";

    footer.appendChild(this.approveBtn);
    footer.appendChild(this.rejectBtn);

    // Hidden rejection feedback
    this.rejectArea = document.createElement("div");
    this.rejectArea.className = "modal-reject-area";
    this.rejectArea.style.display = "none";

    const hint = document.createElement("p");
    hint.className = "modal-reject-hint";
    hint.textContent = "Please provide feedback to guide the agent's revision:";
    this.rejectArea.appendChild(hint);

    this.rejectTextarea = document.createElement("textarea");
    this.rejectTextarea.className = "modal-reject-textarea";
    this.rejectTextarea.placeholder = "Describe what needs to change...";
    this.rejectArea.appendChild(this.rejectTextarea);

    this.sendRejectBtn = document.createElement("button");
    this.sendRejectBtn.className = "confirm-reject";
    this.sendRejectBtn.textContent = "Send Rejection";
    this.sendRejectBtn.disabled = true;
    this.rejectArea.appendChild(this.sendRejectBtn);

    footer.appendChild(this.rejectArea);
    card.appendChild(footer);

    document.body.appendChild(overlay);

    // ── Events ──
    this.approveBtn.addEventListener("click", async () => {
      if (this._confirmed) return;
      this._confirmed = true;
      this.approveBtn.disabled = true;
      this.rejectBtn.disabled = true;
      try {
        if (this._approveCallback) await this._approveCallback();
      } catch (e) {
        console.error("Approval callback failed", e);
        this.approveBtn.disabled = false;
        this.rejectBtn.disabled = false;
        this._confirmed = false;
        return;
      }
      this._closeModal();
    });

    this.rejectBtn.addEventListener("click", () => {
      this.rejectBtn.style.display = "none";
      this.rejectArea.style.display = "block";
      this.rejectTextarea.focus();
    });

    this.rejectTextarea.addEventListener("input", () => {
      this.sendRejectBtn.disabled = this.rejectTextarea.value.trim() === "";
    });

    this.sendRejectBtn.addEventListener("click", () => {
      const reason = this.rejectTextarea.value.trim();
      if (!reason || this._confirmed) return;
      this._confirmed = true;
      this.sendRejectBtn.disabled = true;
      this.rejectTextarea.disabled = true;
      if (this._rejectCallback) this._rejectCallback(reason);
      this._closeModal();
    });
  }

  _esc(text) {
    const div = document.createElement("div");
    div.textContent = text || "";
    return div.innerHTML;
  }

  onApprove(cb) { this._approveCallback = cb; }
  onReject(cb) { this._rejectCallback = cb; }

  destroy() {
    if (this.overlay && this.overlay.parentElement) {
      this.overlay.classList.add("closing");
      setTimeout(() => {
        if (this.overlay.parentElement) this.overlay.remove();
      }, 220);
    }
  }
}
/**
 * CodeReviewPanel - A CodeMirror 5 based code review panel with diff view.
 */
class CodeReviewPanel {
  /**
   * @param {HTMLElement} container
   * @param {string} path
   * @param {string} originalText
   * @param {string} modifiedText
   * @param {string} language
   */
  constructor(container, path, originalText, modifiedText, language) {
    this.container = container;
    this.path = path;
    this.originalText = originalText;
    this.modifiedText = modifiedText;
    this.language = this._mapLanguage(language);
    this.currentMode = "view";
    this._approveCallback = null;
    this._rejectCallback = null;
    // Store per-line gutter markers so we can clear them later
    this._gutterMarkers = [];
    this._init();
  }

  /**
   * Map file extension language to CodeMirror 5 mode.
   * @param {string} lang
   * @returns {string|object}
   */
  _mapLanguage(lang) {
    if (lang === "cpp" || lang === "cc" || lang === "cxx" || lang === "hpp") {
      return { name: "clike", language: "cpp" };
    }
    if (lang === "c" || lang === "h") {
      return { name: "clike", language: "c" };
    }
    if (lang === "java") {
      return { name: "clike", language: "java" };
    }

    const map = {
      python: "python",
      javascript: "javascript",
      typescript: "javascript",
      rust: "rust",
      go: "go",
      html: "htmlmixed",
      htm: "htmlmixed",
      css: "css",
      json: "javascript",
      markdown: "markdown",
      sql: "sql",
    };
    return map[lang] || "python";
  }

  _init() {
    try {
      // DOM
      this.panelDiv = document.createElement("div");
      this.panelDiv.className = "code-review-panel";

      this.headerDiv = document.createElement("div");
      this.headerDiv.className = "code-review-header";
      this.headerDiv.textContent = this.path || "(unknown file)";

      this.editorDiv = document.createElement("div");
      this.editorDiv.className = "code-review-editor";
      this.editorDiv.style.position = "relative";

      this.footerDiv = document.createElement("div");
      this.footerDiv.className = "code-review-footer";

      const approveBtn = document.createElement("button");
      approveBtn.className = "confirm-approve";
      approveBtn.textContent =
        (typeof t !== "undefined" && t("tool.approve")) || "\u2713 Approve";
      const rejectBtn = document.createElement("button");
      rejectBtn.className = "confirm-reject";
      rejectBtn.textContent =
        (typeof t !== "undefined" && t("tool.reject")) || "\u2717 Reject";

      this.footerDiv.appendChild(approveBtn);
      this.footerDiv.appendChild(rejectBtn);

      // Hidden rejection feedback area
      this.rejectArea = document.createElement("div");
      this.rejectArea.className = "code-review-reject-area";
      this.rejectArea.style.display = "none";

      this.rejectHint = document.createElement("p");
      this.rejectHint.className = "code-review-reject-hint";
      this.rejectHint.textContent = "Please provide feedback to guide the agent's revision:";
      this.rejectArea.appendChild(this.rejectHint);

      this.rejectTextarea = document.createElement("textarea");
      this.rejectTextarea.className = "code-review-reject-textarea";
      this.rejectTextarea.placeholder = "Describe what needs to change...";
      this.rejectArea.appendChild(this.rejectTextarea);

      this.sendRejectBtn = document.createElement("button");
      this.sendRejectBtn.className = "confirm-reject";
      this.sendRejectBtn.textContent = "Send Rejection";
      this.sendRejectBtn.disabled = true;
      this.rejectArea.appendChild(this.sendRejectBtn);

      this.footerDiv.appendChild(this.rejectArea);

      this.modeToggleBtn = document.createElement("button");
      this.modeToggleBtn.className = "mode-toggle-btn";
      this.modeToggleBtn.textContent = "\u270E";
      this.modeToggleBtn.title = "Switch to edit mode";

      this.panelDiv.appendChild(this.headerDiv);
      this.panelDiv.appendChild(this.editorDiv);
      this.panelDiv.appendChild(this.footerDiv);
      this.panelDiv.appendChild(this.modeToggleBtn);
      this.container.appendChild(this.panelDiv);

      this.cm = CodeMirror(this.editorDiv, {
        value: this.modifiedText,
        mode: this.language,
        theme: "default",
        lineNumbers: true,
        readOnly: true,
        lineWrapping: true,
        viewportMargin: Infinity,
      });

      this.cm.refresh();

      // Delay diff application to ensure CodeMirror is fully initialised
      setTimeout(() => {
        if (this.cm) {
          this._applyDiff();
        }
      }, 200);

      this.modeToggleBtn.addEventListener("click", () => {
        if (this.currentMode === "view") {
          this.currentMode = "edit";
          this.cm.setOption("readOnly", false);
          this._clearDiff();
          this.modeToggleBtn.textContent = "\uD83D\uDC41";
          this.modeToggleBtn.title = "Switch to view mode";
        } else {
          this.currentMode = "view";
          this.cm.setOption("readOnly", true);
          this._applyDiff();
          this.modeToggleBtn.textContent = "\u270E";
          this.modeToggleBtn.title = "Switch to edit mode";
        }
      });

      approveBtn.addEventListener("click", () => {
        if (this._approveCallback) {
          this._clearDiff();
          this._approveCallback(this.cm.getValue());
        }
      });
      rejectBtn.addEventListener("click", () => {
        rejectBtn.disabled = true;
        this.rejectArea.style.display = "block";
        this.rejectTextarea.focus();
      });

      this.rejectTextarea.addEventListener("input", () => {
        this.sendRejectBtn.disabled = this.rejectTextarea.value.trim() === "";
      });

      this.sendRejectBtn.addEventListener("click", () => {
        const reason = this.rejectTextarea.value.trim();
        if (reason && this._rejectCallback) {
          this.sendRejectBtn.disabled = true;
          this.rejectTextarea.disabled = true;
          this._rejectCallback(reason);
        }
      });
    } catch (initError) {
      console.error("CodeReviewPanel init failed:", initError);
      this.panelDiv = document.createElement("div");
      this.panelDiv.className = "code-review-panel";
      this.panelDiv.innerHTML =
        '<div class="code-review-header">' +
        "Initialization failed" +
        '<button class="code-review-close-btn" style="float:right;background:none;border:none;color:#fff;cursor:pointer;font-size:1rem;">✕</button>' +
        "</div>" +
        '<div class="code-review-editor" style="padding:1rem;color:#dc2626;">' +
        "Error: " +
        initError.message +
        "</div>";
      this.container.appendChild(this.panelDiv);
      this.cm = null;
      // Dismiss button restores layout
      this.panelDiv.querySelector(".code-review-close-btn").addEventListener("click", () => {
        this.container.classList.add("closing");
        setTimeout(() => {
          this.destroy();
          document.getElementById("chat-page").classList.remove("split-layout");
          this.container.remove();
        }, 250);
      });
    }
  }

  /**
   * Apply diff highlights and custom line numbers.
   * Green for additions, red for deletions.
   */
  _applyDiff() {
    if (!this.cm || typeof Diff === "undefined" || !Diff.diffLines) {
      console.warn("[CodeReviewPanel] Diff library not loaded, diff highlighting disabled");
      return;
    }

    // Clear previous gutter markers
    this._clearGutterMarkers();

    const currentText = this.cm.getValue();
    const diffResult = Diff.diffLines(this.originalText, currentText);

    const wasReadOnly = this.cm.getOption("readOnly");
    if (wasReadOnly) this.cm.setOption("readOnly", false);

    try {
      let lineOffset = 0; // Current line in the editor
      let origLine = 1; // Line number in the original file
      let newLine = 1; // Line number in the new file

      for (const part of diffResult) {
        const content = part.value;
        const hasTrailingNewline = content.endsWith("\n");
        const lines = content.split("\n");
        const lineCount = hasTrailingNewline ? lines.length - 1 : lines.length;

        if (part.added) {
          // Added lines: green background + green gutter
          for (let i = 0; i < lineCount; i++) {
            const editorLine = lineOffset + i;
            this.cm.addLineClass(editorLine, "background", "cm-diff-insert");
            this.cm.addLineClass(editorLine, "gutter", "cm-diff-insert-gutter");
            // Custom line number: show new file line number, empty for old
            this._setGutterMarker(editorLine, `${newLine + i}`);
          }
          lineOffset += lineCount;
          newLine += lineCount;
        } else if (part.removed) {
          // Deleted lines: insert the original code as placeholders, then mark red
          const removedCode = hasTrailingNewline
            ? lines.slice(0, -1).join("\n")
            : content;
          this.cm.replaceRange(removedCode + "\n", { line: lineOffset, ch: 0 });
          for (let i = 0; i < lineCount; i++) {
            const editorLine = lineOffset + i;
            this.cm.addLineClass(
              editorLine,
              "background",
              "cm-diff-placeholder",
            );
            this.cm.addLineClass(editorLine, "background", "cm-diff-delete");
            this.cm.addLineClass(editorLine, "gutter", "cm-diff-delete-gutter");
            // Custom line number: show original file line number, empty for new
            this._setGutterMarker(editorLine, `${origLine + i}`);
          }
          lineOffset += lineCount;
          origLine += lineCount;
        } else {
          // Unchanged lines: show both line numbers
          for (let i = 0; i < lineCount; i++) {
            const editorLine = lineOffset + i;
            this._setGutterMarker(editorLine, `${newLine + i}`);
          }
          lineOffset += lineCount;
          origLine += lineCount;
          newLine += lineCount;
        }
      }
    } finally {
      if (wasReadOnly) this.cm.setOption("readOnly", true);
    }
    this.editorDiv.classList.add("cm-preview-mode");
  }

  /**
   * Set a custom text in the line-number gutter for a specific line.
   * @param {number} line - 0‑based line index
   * @param {string} text - The text to display (e.g., "12 / " or " / 15")
   */
  _setGutterMarker(line, text) {
    if (!this.cm) return;
    const marker = document.createElement("div");
    marker.className = "custom-linenumber";
    marker.textContent = text;
    this.cm.setGutterMarker(line, "CodeMirror-linenumbers", marker);
    this._gutterMarkers.push(line);
  }

  /**
   * Remove all custom gutter markers that were previously added.
   */
  _clearGutterMarkers() {
    if (!this.cm) return;
    for (const line of this._gutterMarkers) {
      this.cm.setGutterMarker(line, "CodeMirror-linenumbers", null);
    }
    this._gutterMarkers = [];
  }

  /**
   * Remove all diff decorations and gutter markers.
   */
  _clearDiff() {
    if (!this.cm) return;

    // Remove all placeholder lines that were inserted for deleted code
    const linesToRemove = [];
    const lineCount = this.cm.lineCount();
    for (let i = 0; i < lineCount; i++) {
      const classes = this.cm.lineInfo(i).bgClass || "";
      if (classes.includes("cm-diff-placeholder")) {
        linesToRemove.push(i);
      }
    }
    // Remove from bottom to top to keep line indices valid
    for (let i = linesToRemove.length - 1; i >= 0; i--) {
      const line = linesToRemove[i];
      this.cm.replaceRange("", { line, ch: 0 }, { line: line + 1, ch: 0 });
    }

    // Clear all remaining diff-related classes and gutter markers
    const currentLineCount = this.cm.lineCount();
    for (let i = 0; i < currentLineCount; i++) {
      this.cm.removeLineClass(i, "background", "cm-diff-insert");
      this.cm.removeLineClass(i, "background", "cm-diff-delete");
      this.cm.removeLineClass(i, "background", "cm-diff-placeholder");
      this.cm.removeLineClass(i, "gutter", "cm-diff-insert-gutter");
      this.cm.removeLineClass(i, "gutter", "cm-diff-delete-gutter");
    }

    // Clear custom gutter markers
    this._clearGutterMarkers();
    this.editorDiv.classList.remove("cm-preview-mode");
  }

  /**
   * Switch between view and edit modes.
   * @param {string} mode - "view" or "edit"
   */
  setMode(mode) {
    if (mode === this.currentMode || !this.cm) return;

    if (mode === "edit") {
      this.cm.setOption("readOnly", false);
      this._clearDiff();
      this.currentMode = "edit";
      this.modeToggleBtn.textContent = "\uD83D\uDC41";
      this.modeToggleBtn.title = "Switch to view mode";
    } else {
      this.cm.setOption("readOnly", true);
      this._applyDiff();
      this.currentMode = "view";
      this.modeToggleBtn.textContent = "\u270E";
      this.modeToggleBtn.title = "Switch to edit mode";
    }
  }

  /**
   * Register callback for approval.
   * @param {(finalContent: string) => void} cb
   */
  onApprove(cb) {
    this._approveCallback = cb;
  }

  /**
   * Register callback for rejection.
   * @param {() => void} cb
   */
  onReject(cb) {
    this._rejectCallback = cb;
  }

  /**
   * Safely destroy the CodeMirror instance and remove the panel from the DOM.
   */
  destroy() {
    if (this.cm) {
      try {
        this.cm.toTextArea();
      } catch (e) {
        console.warn("CodeMirror toTextArea failed, cleaning up manually.", e);
        const wrapper = this.cm.getWrapperElement();
        if (wrapper && wrapper.parentNode) {
          wrapper.parentNode.removeChild(wrapper);
        }
      }
      this.cm = null;
    }
    if (this.panelDiv && this.panelDiv.parentElement) {
      this.panelDiv.remove();
    }
  }
}

// ── Review Mode Triggers ──────────────────────────────────────────────────

const REVIEW_MODES = {
  contract_consistency: {
    label: "契约一致性检查",
    icon: "🔗",
    apiMode: "contract_consistency",
  },
  single_step_critique: {
    label: "单步挑刺检查",
    icon: "🔍",
    apiMode: "single_step_critique",
  },
  iteration_drift: {
    label: "迭代脱节检查",
    icon: "⚖️",
    apiMode: "iteration_drift",
  },
};

function showReviewPromptModal(modeKey) {
  const modeInfo = REVIEW_MODES[modeKey];
  if (!modeInfo) return;

  const existing = document.querySelector(".review-modal-overlay");
  if (existing) {
    existing.classList.add("closing");
    setTimeout(function () {
      if (existing.parentElement) existing.remove();
    }, 220);
  }

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay review-modal-overlay";
  const card = document.createElement("div");
  card.className = "modal-card";
  overlay.appendChild(card);

  function close() {
    overlay.classList.add("closing");
    setTimeout(function () {
      if (overlay.parentElement) overlay.remove();
    }, 220);
  }

  overlay.addEventListener("click", function (e) {
    if (e.target === overlay) close();
  });
  document.addEventListener("keydown", function onEsc(e) {
    if (e.key === "Escape") {
      close();
      document.removeEventListener("keydown", onEsc);
    }
  });

  // Header
  var header = document.createElement("div");
  header.className = "modal-card-header";
  header.innerHTML =
    '<div class="modal-card-header-left">' +
    '<span class="phase-badge-sm" style="background:#8b5cf6;">' +
    modeInfo.icon + " " + modeInfo.label +
    "</span></div>";
  var closeBtn = document.createElement("button");
  closeBtn.className = "modal-card-close";
  closeBtn.innerHTML = "&#10005;";
  closeBtn.addEventListener("click", close);
  header.appendChild(closeBtn);
  card.appendChild(header);

  // Body
  var body = document.createElement("div");
  body.className = "modal-card-body review-modal-body";
  var hintLabel = (typeof t !== "undefined" && t("review.inject_prompt_hint"))
    ? t("review.inject_prompt_hint") : "是否注入提示？";
  var hintDesc = (typeof t !== "undefined" && t("review.prompt_hint_desc"))
    ? t("review.prompt_hint_desc") : "(可选：为审查提供额外上下文和关注方向)";
  var hintPlaceholder = (typeof t !== "undefined" && t("review.prompt_hint_placeholder"))
    ? t("review.prompt_hint_placeholder") : "例如：请特别关注安全性、边界条件和性能...（留空则使用默认审查策略）";
  body.innerHTML =
    '<p class="review-modal-question">' +
    "<strong>" + modeInfo.label + "</strong> — " + hintLabel +
    '<span class="review-modal-hint-desc">' + hintDesc + "</span></p>" +
    '<textarea id="review-prompt-hint-input" class="review-modal-textarea" ' +
    'placeholder="' + hintPlaceholder + '" rows="4"></textarea>';
  card.appendChild(body);

  // Footer
  var footer = document.createElement("div");
  footer.className = "modal-card-footer";
  var runLabel = (typeof t !== "undefined" && t("review.run"))
    ? t("review.run") : "运行审查";
  var cancelLabel = (typeof t !== "undefined" && t("review.cancel"))
    ? t("review.cancel") : "取消";

  var runBtn = document.createElement("button");
  runBtn.className = "confirm-approve";
  runBtn.textContent = runLabel;
  runBtn.addEventListener("click", function () {
    var ta = document.getElementById("review-prompt-hint-input");
    var promptHint = ta ? ta.value.trim() : "";
    close();
    triggerReview(modeKey, promptHint);
  });

  var cancelBtn = document.createElement("button");
  cancelBtn.className = "confirm-reject";
  cancelBtn.style.background = "#94a3b8";
  cancelBtn.textContent = cancelLabel;
  cancelBtn.addEventListener("click", close);

  footer.appendChild(runBtn);
  footer.appendChild(cancelBtn);
  card.appendChild(footer);

  document.body.appendChild(overlay);

  setTimeout(function () {
    var ta = document.getElementById("review-prompt-hint-input");
    if (ta) ta.focus();
  }, 300);
}

function triggerReview(modeKey, promptHint) {
  var modeInfo = REVIEW_MODES[modeKey];
  if (!modeInfo) return;

  var runningLabel = (typeof t !== "undefined" && t("review.running"))
    ? t("review.running", { mode: modeInfo.label }) : "Running review: " + modeInfo.label;
  var loadingMsg = addMessage(
    "assistant",
    modeInfo.icon + " " + runningLabel + "...",
    true,
    "review-loading",
    false
  );
  scrollToBottom();

  fetchWithAuth("/api/review", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode: modeInfo.apiMode,
      project_id: "",
      phase: "",
      module: "",
      prompt_hint: promptHint,
    }),
  })
    .then(function (resp) { return resp.json(); })
    .then(function (data) {
      if (loadingMsg.parentElement) loadingMsg.remove();
      if (data.status === "ok" && data.report) {
        addReviewReportMessage(modeInfo, data.report);
      } else {
        addMessage(
          "assistant",
          modeInfo.icon + " **" + modeInfo.label + "** failed: " + (data.error || "Unknown error"),
          false,
          "review-error",
          true
        );
      }
      scrollToBottom();
    })
    .catch(function (err) {
      if (loadingMsg.parentElement) loadingMsg.remove();
      addMessage(
        "assistant",
        modeInfo.icon + " **" + modeInfo.label + "** network error: " + err.message,
        false,
        "review-error",
        true
      );
      scrollToBottom();
    });
}

function addReviewReportMessage(modeInfo, markdownReport) {
  var msgDiv = document.createElement("div");
  msgDiv.className = "message assistant review-report-message";

  var headerBadge = document.createElement("div");
  headerBadge.className = "review-report-header";
  headerBadge.innerHTML =
    '<span class="review-report-badge">' +
    modeInfo.icon + " " + modeInfo.label + "</span>" +
    '<span class="review-report-timestamp">' +
    new Date().toLocaleTimeString() + "</span>";
  msgDiv.appendChild(headerBadge);

  var contentDiv = document.createElement("div");
  contentDiv.className = "assistant-content review-report-content";
  renderFullMarkdown(contentDiv, markdownReport);
  msgDiv.appendChild(contentDiv);

  chatMessages.appendChild(msgDiv);
  saveMessagesToLocalStorage();
  scrollToBottom();
  return msgDiv;
}

// ── Review button bindings ─────────────────────────────────────────────────
(function () {
  var btnContract = document.getElementById("btn-review-contract");
  var btnCritique = document.getElementById("btn-review-critique");
  var btnDrift = document.getElementById("btn-review-drift");

  if (btnContract) {
    btnContract.addEventListener("click", function () {
      showReviewPromptModal("contract_consistency");
    });
  }
  if (btnCritique) {
    btnCritique.addEventListener("click", function () {
      showReviewPromptModal("single_step_critique");
    });
  }
  if (btnDrift) {
    btnDrift.addEventListener("click", function () {
      showReviewPromptModal("iteration_drift");
    });
  }
})();
