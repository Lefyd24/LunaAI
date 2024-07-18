const chatInput = document.querySelector("#chat-input");
const sendButton = document.querySelector("#send-btn");
const chatContainer = document.querySelector(".chat-container");
const themeButton = document.querySelector("#theme-btn");
const deleteButton = document.querySelector("#delete-btn");
const fileUploadButton = document.querySelector("#file-upload-btn");
const fileInput = document.querySelector("#file-input");
const uploadFilesButton = document.querySelector("#upload-files-btn");
const fileListDiv = document.querySelector("#file-list");
const loadingSpinner = document.querySelector("#loading-spinner");
const conversationsList = document.querySelector("#conversations-list");
const channelSelect = document.querySelector("#channel-select");
const internetSearchCheckbox = document.querySelector("#internet-search-checkbox");

function formatMessageContent(content) {
    const codeBlockPattern = /```(python)\s([\s\S]*?)```/g;
    const falseHtmlPattern = /```(html)\s([\s\S]*?) /g;
    const pythonFunctionPattern = /def (\w+)\(.*\):/g;

    content = content.replace(falseHtmlPattern, "");
    content = content.replace(codeBlockPattern, (match, p1, p2) => {
        const formattedCode = p2.replace(/#(.*)/g, '<code class="comment">#$1</code>');
        return `<pre><code class="${p1}">${formattedCode}</code></pre>`;
    });
    return content;
}

document.addEventListener('DOMContentLoaded', () => {
    const socket = io();
    
    socket.on('joined_room', (data) => {
        const { username, room } = data;
        const formattedRoom = room.charAt(0).toUpperCase() + room.slice(1);
        document.title = `Luna A.I. - ${formattedRoom}`;
        const defaultText = `<div class="default-text">
                                <img src="static/svgs/luna-ai-high-resolution-logo-transparent.svg" alt="logo" width="200px">
                                <p>You are currently in the room: <strong>${formattedRoom}</strong></p>
                                <p>Start a conversation and explore the power of AI.<br> Your chat history will be displayed here.</p>
                            </div>`;

        chatContainer.innerHTML = defaultText;
        chatContainer.scrollTo(0, chatContainer.scrollHeight);

        let userText = null;

        const loadConversations = async () => {
            try {
                const response = await fetch(`/conversations/${username}`);
                const conversations = await response.json();
                for (const room in conversations) {
                    conversations[room].forEach(convoId => {
                        const convoElement = document.createElement('li');
                        convoElement.dataset.id = convoId;
                        convoElement.dataset.room = room;
                        convoElement.textContent = convoId;
                        conversationsList.appendChild(convoElement);
                    });
                }
            } catch (error) {
                console.error('Error loading conversations:', error);
            }
        };

        const loadConversationHistory = async (roomId, conversationId) => {
            try {
                const response = await fetch(`/history/${username}/${roomId}/${conversationId}`);
                const chatHistory = await response.json();
                chatContainer.innerHTML = '';
                chatHistory.forEach(message => {
                    const chatClass = message.sender === username ? 'outgoing' : 'incoming';
                    const imgSrc = chatClass === 'outgoing' ? 'user.webp' : 'chatbot.webp';
                    let chatHtml = '';
                    if (chatClass === 'incoming') {
                        chatHtml = `
                        <div class="chat-content">
                            <div class="chat-details">
                                <img src="static/images/${imgSrc}" alt="${chatClass}-img">
                                <div class='chat-response'>
                                    <div class='response'>${message.msg}</div>
                                    <div class='sources'></div>
                                </div>
                            </div>
                        </div>`;
                    } else {
                        chatHtml = `
                            <div class="chat-content">
                                <div class="chat-details">
                                    <img src="static/images/${imgSrc}" alt="${chatClass}-img">
                                    <p>${message.msg}</p>
                                </div>
                            </div>`;
                    }
                    const chatElement = createChatElement(chatHtml, chatClass, message.id);
                    chatContainer.appendChild(chatElement);
                });
                chatContainer.scrollTo(0, chatContainer.scrollHeight);
            } catch (error) {
                console.error('Error loading conversation history:', error);
            }
        };

        const createChatElement = (content, className, id) => {
            const chatDiv = document.createElement("div");
            chatDiv.classList.add("chat", className);
            chatDiv.innerHTML = content;
            chatDiv.id = id; 
            return chatDiv;
        };

        const getChatResponse = (incomingChatDiv, messageId) => {
            const responseDiv = document.createElement("div");
            responseDiv.classList.add("response-container");
            const responseElement = document.createElement("div");
            responseElement.classList.add("bot-text");
            const sourcesElement = document.createElement("div");
            sourcesElement.classList.add("sources");
            const newTypingAnimationContainer = document.createElement("div");
            newTypingAnimationContainer.classList.add("new-typing-animation-container");
            const newTypingAnimation = document.createElement("div");
            newTypingAnimation.classList.add("new-typing-animation");
            newTypingAnimationContainer.appendChild(newTypingAnimation);

            const seachTheWeb = internetSearchCheckbox.checked;
        
            let htmlBuffer = "";
            let messageData = {
                msg: userText,
                room: room,
                sender: username,
                internetSearch: seachTheWeb,
                messageId: messageId
            };
            socket.emit('message', messageData);
            
            // Disable input while streaming response
            chatInput.disabled = true;
            sendButton.disabled = true;
            chatInput.classList.add("disabled");

            socket.on(`message_chunk_${messageId}`, (data) => {
                if (data.chunk === 'response_start') {
                    const typingAnimation = incomingChatDiv.querySelector(".typing-animation");
                    if (typingAnimation) {
                        typingAnimation.remove();
                    }
                    responseDiv.appendChild(newTypingAnimationContainer);
                    incomingChatDiv.querySelector(".chat-details").appendChild(responseDiv);
                } else if (data.chunk === 'response_end') {
                    htmlBuffer = "";
                } else {
                    htmlBuffer += data.chunk;
                    responseElement.innerHTML = formatMessageContent(htmlBuffer);
                    if (!responseDiv.contains(responseElement)) {
                        responseDiv.insertBefore(responseElement, newTypingAnimationContainer);
                    }
                }
            });
        
            // sources
            socket.on(`message_chunk_${messageId}_sources`, (data) => {
                sourcesElement.innerHTML = '<strong>Sources:</strong>';
                for (const source in data.sources) {
                    if (data.sources.hasOwnProperty(source)) {
                        const pages = data.sources[source].pages.length > 0 ? ` (pages: ${data.sources[source].pages.join(', ')})` : '';
                        const sourceElement = document.createElement('p');
                        sourceElement.innerHTML = `<a href="${source}" target="_blank">${source}${pages}</a>`;
                        sourcesElement.appendChild(sourceElement);
                    }
                }
                responseDiv.appendChild(sourcesElement);
                
                // Enable input and remove typing animation after sources arrive
                chatInput.disabled = false;
                sendButton.disabled = false;
                chatInput.classList.remove("disabled");
                const typingAnimation = incomingChatDiv.querySelector(".new-typing-animation-container");
                if (typingAnimation) {
                    typingAnimation.remove();
                }
            });
        
            chatContainer.scrollTo(0, chatContainer.scrollHeight);
        };
        
        const copyResponse = (event) => { // this copies only the first response no matter how many responses are there
            const copyBtn = event.currentTarget;
            // Copy the text content of the response to the clipboard
            const reponseTextElement = copyBtn.parentElement.querySelector('.bot-text');
            navigator.clipboard.writeText(reponseTextElement.textContent);
            // change the icon to checkmark with a delay
            const actualCopyIcon = copyBtn.parentElement.querySelector('.material-symbols-rounded');
            // set the icon to checkmark with a delay
            actualCopyIcon.textContent = 'done';
            setTimeout(() => {
                actualCopyIcon.textContent = 'content_copy';
            }, 3000);
             
        };

        const showTypingAnimation = (messageId) => {
            const html = `<div class="chat-content">
                            <div class="chat-details">
                                <img src="static/images/chatbot.webp" alt="chatbot-img">
                                <div class="typing-animation">
                                    <div class="typing-dot" style="--delay: 0.2s"></div>
                                    <div class="typing-dot" style="--delay: 0.3s"></div>
                                    <div class="typing-dot" style="--delay: 0.4s"></div>
                                </div>
                            </div>
                            <span class="material-symbols-rounded copy-btn">content_copy</span>
                        </div>`;
            const incomingChatDiv = createChatElement(html, "incoming", messageId);
            chatContainer.appendChild(incomingChatDiv);
            chatContainer.scrollTo(0, chatContainer.scrollHeight);
            getChatResponse(incomingChatDiv, messageId);
        };

        const handleOutgoingChat = () => {
            userText = chatInput.value.trim();
            if (!userText) return;

            chatInput.value = "";
            chatInput.style.height = `${initialInputHeight}px`;

            const messageId = `msg-${Date.now()}`;

            const html = `<div class="chat-content">
                            <div class="chat-details">
                                <img src="static/images/user.webp" alt="user-img">
                                <div class='user-text'>${userText}</div>
                            </div>
                        </div>`;

            const outgoingChatDiv = createChatElement(html, "outgoing", messageId);
            chatContainer.querySelector(".default-text")?.remove();
            chatContainer.appendChild(outgoingChatDiv);
            chatContainer.scrollTo(0, chatContainer.scrollHeight);
            setTimeout(() => showTypingAnimation(messageId), 500);
        };

        const handleFileUpload = () => {
            fileInput.click();
        };

        const handleFileSelection = () => {
            fileListDiv.innerHTML = '';
            if (fileInput.files.length > 0) {
                fileListDiv.style.display = 'block';
                uploadFilesButton.style.display = 'block';
                for (const file of fileInput.files) {
                    const fileElement = document.createElement('p');
                    fileElement.textContent = file.name;
                    fileListDiv.appendChild(fileElement);
                }
            } else {
                fileListDiv.style.display = 'none';
                uploadFilesButton.style.display = 'none';
            }
        };

        const handleFileUploadSubmit = async () => {
            loadingSpinner.style.display = 'flex';
            const formData = new FormData();
            for (const file of fileInput.files) {
                formData.append('files', file);
            }
            try {
                const response = await fetch('/upload', {
                    method: 'POST',
                    body: formData
                });
                if (response.ok) {
                    alert('Files uploaded successfully.');
                    uploadFilesButton.style.display = 'none';
                    fileListDiv.style.display = 'none';
                    fileInput.value = '';
                } else {
                    alert('Failed to upload files.');
                }
            } catch (error) {
                console.error('Error uploading files:', error);
            } finally {
                loadingSpinner.style.display = 'none';
            }
        };

        const loadChannels = async () => {
            try {
                socket.emit('get_channels', { username });
                socket.on('channels', (channels) => {
                    for (const room in channels) {
                        const option = document.createElement('option');
                        option.value = channels[room];
                        option.textContent = channels[room].charAt(0).toUpperCase() + channels[room].slice(1);
                        if (channels[room] === data.room) {
                            option.selected = true;
                        }
                        channelSelect.appendChild(option);
                    }
                    const option = document.createElement('option');
                    option.value = 'new_channel';
                    option.innerHTML = '&#43; New Channel';
                    channelSelect.appendChild(option);
                });
            } catch (error) {
                console.error('Error loading channels:', error);
            }
        };

        channelSelect.addEventListener('change', (event) => {
            const newRoom = event.target.value;
            if (newRoom) {
                if (newRoom === 'new_channel') {
                    const newChannelName = prompt('Enter the name of the new channel:');
                    if (newChannelName) {
                        socket.emit('create_channel', { username, newChannelName });
                        socket.emit('leave', { username, room });
                        window.location.href = `/?username=${username}&room=${newChannelName}`;
                    } else {
                        return;
                    }
                } else {
                    socket.emit('leave', { username, room });
                    window.location.href = `/?username=${username}&room=${newRoom}`;
                }
            }
        });

        const initialInputHeight = chatInput.scrollHeight;

        chatInput.addEventListener("input", () => {
            chatInput.style.height = `${initialInputHeight}px`;
            chatInput.style.height = `${chatInput.scrollHeight}px`;
        });

        chatInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey && window.innerWidth > 800) {
                e.preventDefault();
                handleOutgoingChat();
            }
        });

        conversationsList.addEventListener("click", (event) => {
            const roomId = event.target.dataset.room;
            const conversationId = event.target.dataset.id;
            loadConversationHistory(roomId, conversationId);
        });

        sendButton.addEventListener("click", handleOutgoingChat);
        fileUploadButton.addEventListener("click", handleFileUpload);
        fileInput.addEventListener("change", handleFileSelection);
        uploadFilesButton.addEventListener("click", handleFileUploadSubmit);

        themeButton.addEventListener("click", () => {
            document.body.classList.toggle("light-mode");
            themeButton.innerText = document.body.classList.contains("light-mode") ? "dark_mode" : "light_mode";
        });

        deleteButton.addEventListener("click", () => {
            if (confirm("Are you sure you want to delete all the chats?")) {
                chatContainer.innerHTML = `<div class="default-text">
                                    <h1>Lefteris' Personal A.I.</h1>
                                    <p>Start a conversation and explore the power of AI.<br> Your chat history will be displayed here.</p>
                                </div>`;
            }
        });

        loadConversations();
        loadChannels();

        // Add event listener for copy buttons
        chatContainer.addEventListener('click', (event) => {
            if (event.target.classList.contains('copy-btn')) {
                copyResponse(event);
            }
        });
        
        
    });

    const urlParams = new URLSearchParams(window.location.search);
    const username = urlParams.get('username');
    const room = urlParams.get('room');
    socket.emit('join', { username, room });
});
