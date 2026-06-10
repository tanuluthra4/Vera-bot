const sendBtn = document.getElementById("sendBtn");
const input = document.getElementById("messageInput");
const chatMessages = document.getElementById("chat-messages");

function addMessage(message, type) {
    const div = document.createElement("div");

    div.classList.add("message");
    div.classList.add(type);

    div.textContent = message;

    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function sendMessage() {
    const text = input.value.trim();

    if (!text) return;

    addMessage(text, "user-message");

    input.value = "";

    try {
        const response = await fetch("/chat", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                message: text
            })
        });

        const data = await response.json();

        addMessage(data.reply, "bot-message");

    } catch (error) {
        addMessage("Backend connection failed.", "bot-message");
        console.error(error);
    }
}

sendBtn.addEventListener("click", sendMessage);

input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
        sendMessage();
    }
});