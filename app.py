from flask import Flask, request, jsonify, render_template, redirect, send_from_directory, url_for
import os
import json
from rag import get_model_version  
from flask_socketio import SocketIO, join_room, leave_room, send, emit
import datetime as dt
from uuid import uuid4
from werkzeug.utils import secure_filename


app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['UPLOAD_FOLDER'] = 'uploads'
socketio = SocketIO(app)
CHAT_HISTORY_FILE = 'chat_history.json'

ragmodel = get_model_version("config.yml", "CohereModels", "luna-1")
print(ragmodel)
# Load existing chat history from JSON file or initialize an empty dictionary
if os.path.exists(CHAT_HISTORY_FILE):
    with open(CHAT_HISTORY_FILE, 'r') as file:
        chat_history = json.load(file)
else:
    chat_history = {}

def save_chat_history():
    with open(CHAT_HISTORY_FILE, 'w') as file:
        json.dump(chat_history, file)

@app.route('/')
def index():
    if 'username' in request.args and 'room' in request.args:
        return render_template('index.html', username=request.args['username'], room=request.args['room'])
    else:
        return redirect(url_for('login'))

@app.route('/login')
def login():
    return render_template('login.html')

@socketio.on('join')
def on_join(data):
    username = data['username']
    room = data['room']
    join_room(room)
    ragmodel.set_topic(room)
    ragmodel.set_user(username)
    ragmodel.chat_history = []
    if username not in chat_history:
        chat_history[username] = {}
    if room not in chat_history[username]:
        chat_history[username][room] = {}

    message = {
        'msg': f'{username} has entered the room.',
        'sender': 'System',
        'timestamp': dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    send(message, to=room)

    # Send the join acknowledgment with username and room
    socketio.emit('joined_room', {'username': username, 'room': room}, room=request.sid)

@socketio.on('message')
def handle_message(data):
    room = data['room']
    msg = data['msg']
    sender = data['sender']
    internet_search = data['internetSearch']
    message_id = data.get('messageId')
    print(room, msg, sender, internet_search, message_id)
    conversation_id = data.get('conversation_id')
    timestamp = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if not conversation_id:
        conversation_id = str(uuid4())
        if sender in chat_history:
            if room in chat_history[sender]:
                chat_history[sender][room][conversation_id] = []
            else:
                chat_history[sender][room] = {conversation_id: []}
        else:
            chat_history[sender] = {room: {conversation_id: []}}
        socketio.emit('new_conversation_id', conversation_id, room=request.sid)
    else:
        if sender not in chat_history:
            chat_history[sender] = {}
        if room not in chat_history[sender]:
            chat_history[sender][room] = {}
        if conversation_id not in chat_history[sender][room]:
            chat_history[sender][room][conversation_id] = []

    message = {'msg': msg, 'sender': sender, 'timestamp': timestamp, 'message_id': message_id}
    chat_history[sender][room][conversation_id].append(message)
    save_chat_history()
    send(message, to=room)

    # Generate a response from the RagModel and stream it
    response_message = {'msg': '', 'sender': 'Mitsis A.I. Assistant', 'timestamp': dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    emit('message', response_message, room=room)  # Send a placeholder message to create the element

    response_chunks = ragmodel.generate_stream_response(query=msg, search_web=internet_search)

    with open('response.txt', 'a', encoding='utf-8') as file:
        sources = None
        first_chunk = True
        for chunk in response_chunks:
            if first_chunk:
                emit(f'message_chunk_{message_id}', {'chunk': 'response_start'}, room=room)
                first_chunk = False
            if chunk == "response_end":
                emit(f'message_chunk_{message_id}', {'chunk': chunk}, room=room)
            elif isinstance(chunk, dict):
                sources = chunk
            else:
                emit(f'message_chunk_{message_id}', {'chunk': chunk}, room=room)
                response_message['msg'] += chunk
                file.write(chunk)
        file.write('\n')

    if sources:
        emit(f'message_chunk_{message_id}_sources', {'sources': sources}, room=room)
        print(sources)
    else:
        emit(f'message_chunk_{message_id}_sources', {'sources': {}}, room=room)
    chat_history[sender][room][conversation_id].append(response_message)
    save_chat_history()


@socketio.on('leave')
def on_leave(data):
    username = data['username']
    room = data['room']
    leave_room(room)
    message = {
        'msg': f'{username} has left the room.',
        'sender': 'System',
        'timestamp': dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    if username in chat_history and room in chat_history[username]:
        chat_history[username][room].append(message)
    send(message, to=room)

@socketio.on('get_channels')
def get_channels(data):
    CHANNELS = ragmodel.CHANNELS
    emit('channels', CHANNELS, room=request.sid)

@socketio.on('create_channel')
def create_channel(data):
    print(data)
    user = data['username']
    channel = data['newChannelName']
    print(f"User {user} is creating a new channel: {channel}")
    channel = channel.lower().replace(' ', '_')
    if channel not in ragmodel.CHANNELS:
        ragmodel.add_channel(channel)
        emit('channels', ragmodel.CHANNELS, broadcast=True)


@app.route('/upload', methods=['POST'])
def upload():
    if 'files' not in request.files:
        return "No files part", 400

    files = request.files.getlist('files')
    print(files)
    if not files:
        return "No selected files", 400

    for file in files:
        if file.filename == '':
            return "One or more files have no selected file", 400

        if file:
            # Save the file to the temporary directory
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            doc = ragmodel.load_document(path=filepath)
            splitted_doc = ragmodel.split_text(doc)
            ragmodel.add_document_to_vectorstore(splitted_doc)
          

    return "Files uploaded and processed successfully.", 200

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/save_response', methods=['POST'])
def save_response():
    data = request.get_json()
    content = data.get('content')
    user = data.get('user')
    room = data.get('room')

    if not content or not user or not room:
        return jsonify({'message': 'Invalid data'}), 400
    
    # save the response to a txt file
    with open(os.path.join(app.config['UPLOAD_FOLDER'], f'{user}_{room}.txt'), 'w') as file:
        file.write(content)

    doc = ragmodel.load_document(path=os.path.join(app.config['UPLOAD_FOLDER'], f'{user}_{room}.txt'))
    splitted_doc = ragmodel.split_text(doc)
    ragmodel.add_document_to_vectorstore(splitted_doc)

    return jsonify({'message': 'Response saved successfully'}), 200


@app.route('/history/<username>/<room>/<conversation_id>')
def get_history(username, room, conversation_id):
    if username in chat_history and room in chat_history[username]:
        if conversation_id in chat_history[username][room]:
            return jsonify(chat_history[username][room][conversation_id])
    return jsonify([])

@app.route('/conversations/<username>')
def get_conversations(username):
    if username in chat_history:
        return jsonify({
            room: list(chat_history[username][room].keys())
            for room in chat_history[username] if isinstance(chat_history[username][room], dict)
        })
    return jsonify({})


if __name__ == '__main__':
    socketio.run(app, debug=True, port=5050)