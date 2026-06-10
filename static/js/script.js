const sendBtn = document.getElementById("sendBtn");
const input = document.getElementById("messageInput");
const chatMessages = document.getElementById("chat-messages");

function addUserMessage(message){

    const div = document.createElement("div");

    div.classList.add("message");
    div.classList.add("user-message");

    div.textContent = message;

    chatMessages.appendChild(div);

    chatMessages.scrollTop = chatMessages.scrollHeight;
}

sendBtn.addEventListener("click", () => {

    const text = input.value.trim();

    if(!text) return;

    addUserMessage(text);

    input.value = "";
});

input.addEventListener("keydown", (e) => {

    if(e.key === "Enter"){
        sendBtn.click();
    }

});