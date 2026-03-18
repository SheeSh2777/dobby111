document.addEventListener("DOMContentLoaded", () => {
  if (typeof PROMPT_LIBRARY !== 'undefined') {
    PROMPT_LIBRARY.forEach(p => {
      const promptList = document.getElementById('promptList');
      if (promptList) promptList.appendChild(new Option(p, p));
    });
  }

  populateSelect("designSize", ["Micro", "Small", "Medium", "Large", "Full Size"]);
  populateSelect("designStyle", ["Regular", "Gradational", "Fil-a-Fil", "Counter", "Multicolor", "Solid"]);
  populateSelect("weave", ["Plain", "Twill", "Oxford", "Dobby"]);
  populateSelect("contrastLevel", ["Low", "Medium", "High"]);
  populateSelect("occasion", ["Formal", "Casual", "Party Wear"]);
});

function populateSelect(id, arr) {
  const el = document.getElementById(id);
  if (!el) return;
  arr.forEach(v => el.appendChild(new Option(v, v)));
}

function switchInputMode(mode) {
  const promptContainer = document.getElementById('promptContainer');
  const imageContainer = document.getElementById('imageContainer');

  if (promptContainer) promptContainer.style.display = mode === "prompt" ? "block" : "none";
  if (imageContainer) imageContainer.style.display = mode === "image" ? "block" : "none";
}

let chatHistory = [];
let conversationMessages = [];

function addChatMessage(role, text) {
  chatHistory.push({ role, text });
  renderChat();
}

function renderChat() {
  const chatMessages = document.getElementById('chatMessages');
  if (!chatMessages) return;
  chatMessages.innerHTML = '';

  chatHistory.forEach(item => {
    const messageElem = document.createElement('div');
    messageElem.className = item.role === 'user' ? 'chat-message user' : 'chat-message bot';
    messageElem.textContent = item.text;
    chatMessages.appendChild(messageElem);
  });

  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function switchInputMode(mode) {
  const promptContainer = document.getElementById('promptContainer');
  const imageContainer = document.getElementById('imageContainer');
  const chatContainer = document.getElementById('chatContainer');

  if (promptContainer) promptContainer.style.display = mode === 'prompt' ? 'block' : 'none';
  if (chatContainer) chatContainer.style.display = mode === 'prompt' ? 'block' : 'none';
  if (imageContainer) imageContainer.style.display = mode === 'image' ? 'block' : 'none';
}

function clearChat() {
  const input = document.getElementById('chatInput');
  if (input) input.value = '';
}

function onImageSelected() {
  const imageInput = document.getElementById('imageInput');
  const imageInfo = document.getElementById('imageInfo');

  if (imageInfo && imageInput) {
    imageInfo.textContent = imageInput.files.length
      ? "Selected: " + imageInput.files[0].name
      : "";
  }
}

async function sendChat() {
  const chatInput = document.getElementById("chatInput");
  const btn = document.getElementById("generateBtn");
  if (!chatInput || !chatInput.value.trim()) return;

  const prompt = chatInput.value.trim();
  addChatMessage('user', prompt);
  chatInput.value = '';

  // add system prompt to conversation if first message
  if (conversationMessages.length === 0) {
    conversationMessages.push({ role: 'system', content: `You are a professional textile and yarn pattern identification expert and technical advisor. Answer with practical recommendations, ask clarifying questions, and provide the best solution in the context of yarn and fabric design.` });
  }

  // add user message to conversation history for multi-turn context
  conversationMessages.push({ role: 'user', content: prompt });

  // Loading state
  const prevText = btn.textContent;
  btn.textContent = "Thinking...";
  btn.disabled = true;
  document.body.style.cursor = "wait";

  try {
    const response = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: conversationMessages })
    });

    const data = await response.json();

    if (data.error) {
      throw new Error(data.error);
    }

    let botText = "Hi! I'm your textile assistant. Ask me anything about yarn, patterns, or fabric construction.";

    // Apply structured data to the form if available
    if (data.structured) {
      applyData(data.structured);
      botText = "I've updated the design parameters and material suggestions based on your request.";
    }

    // If provider gives a natural language reply, use it to keep conversation interactive
    if (data.reply) {
      const raw = data.reply.trim();
      const isJson = raw.startsWith('{') || raw.startsWith('[');
      if (!isJson) {
        botText = raw;
      } else if (data.structured) {
        botText = "I have updated the structured design details. What else would you like to refine (e.g., yarn count, color mix, or weave type)?";
      }
    }

    // Encourage follow-up questions
    if (conversationMessages.length > 0) {
      botText += "\n\n(Feel free to ask for recommendations, production constraints, or style variations.)";
    }

    addChatMessage('assistant', botText);
    conversationMessages.push({ role: 'assistant', content: botText });

  } catch (error) {
    console.error("Error:", error);
    addChatMessage('assistant', "Error: " + error.message);
  } finally {
    btn.textContent = prevText;
    btn.disabled = false;
    document.body.style.cursor = "default";
  }
}

async function getFromPrompt() {
  const promptInput = document.getElementById("promptInput");
  const generateBtn = document.getElementById("generateBtnPrompt");

  const prompt = promptInput.value.trim();
  if (!prompt) return alert("Enter or select a prompt");

  // Loading State
  const originalText = generateBtn.textContent;
  generateBtn.textContent = "Generating Design...";
  generateBtn.disabled = true;
  document.body.style.cursor = "wait";

  try {
    const response = await fetch('/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        messages: [
          { role: "user", content: prompt }
        ]
      })
    });

    const data = await response.json();

    if (data.error) {
      throw new Error(data.error);
    }

    if (data.structured) {
      applyData(data.structured);
    } else {
      alert("Could not generate structured textile data. Raw response: " + data.reply);
      console.error("Raw reply:", data.reply);
    }

  } catch (error) {
    console.error("Error:", error);
    alert("Failed to generate design: " + error.message);
  } finally {
    generateBtn.textContent = originalText;
    generateBtn.disabled = false;
    document.body.style.cursor = "default";
  }
}

function getFromImage() {
  alert("Image API will be integrated later. Please use the prompt input for now.");
}

function applyData(d) {
  // Helper to safely set values
  const setVal = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.value = val;
  };
  const setCheck = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.checked = val;
  };

  if (!d || !d.design) {
    console.error("Invalid data structure", d);
    return;
  }

  setVal("designSize", d.design.designSize);
  setVal("designSizeMin", d.design.designSizeRangeCm?.min || 0);
  setVal("designSizeMax", d.design.designSizeRangeCm?.max || 0);
  setVal("designStyle", d.design.designStyle);
  setVal("weave", d.design.weave);

  setVal("stripeSizeMin", d.stripe?.stripeSizeRangeMm?.min || 0);
  setVal("stripeSizeMax", d.stripe?.stripeSizeRangeMm?.max || 0);
  setVal("stripeRepeatMin", d.stripe?.stripeMultiplyRange?.min || 1);
  setVal("stripeRepeatMax", d.stripe?.stripeMultiplyRange?.max || 1);
  setCheck("isSymmetry", d.stripe?.isSymmetry || false);

  setVal("contrastLevel", d.visual?.contrastLevel || "Medium");
  setVal("occasion", d.market?.occasion || "Formal");

  if (d.colors && Array.isArray(d.colors)) {
    const colorStr = d.colors.map(c => `${c.name} (${c.percentage}%)`).join(", ");
    setVal("colorComposition", colorStr);
  }

  // Update Summary Box
  const summaryBox = document.getElementById("summaryBox");
  const colorVal = document.getElementById("colorComposition").value;

  if (summaryBox) {
    summaryBox.innerHTML = `
        <p><b>Design Style:</b> ${d.design.designStyle}</p>
        <p><b>Weave:</b> ${d.design.weave}</p>
        <p><b>Stripe Size:</b> ${d.stripe?.stripeSizeRangeMm?.min}-${d.stripe?.stripeSizeRangeMm?.max} mm</p>
        <p><b>Stripe Repeat:</b> ${d.stripe?.stripeMultiplyRange?.min}-${d.stripe?.stripeMultiplyRange?.max}</p>
        <p><b>Symmetry:</b> ${d.stripe?.isSymmetry ? "Yes" : "No"}</p>
        <p><b>Colors:</b> ${colorVal}</p>
        <p><b>Occasion:</b> ${d.market?.occasion}</p>
        <hr style="margin: 8px 0; border: 0; border-top: 1px solid #eee;">
        <p><b>Technical Specs:</b></p>
        <p><b>Construction:</b> ${d.technical?.construction || "N/A"}</p>
        <p><b>Yarn Count:</b> ${d.technical?.yarnCount || "N/A"}</p>
        <p><b>GSM:</b> ${d.technical?.gsm || "N/A"}</p>
      `;
  }

  // Update JSON Box
  const jsonBox = document.getElementById("jsonBox");
  if (jsonBox) {
    jsonBox.textContent = JSON.stringify(d, null, 2);
  }
}

function clearPrompt() {
  const input = document.getElementById("promptInput");
  if (input) {
    input.value = "";
    input.focus();
  }
}
