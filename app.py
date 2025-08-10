from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO, emit
from gtts import gTTS
import json
import os
import threading
import queue
import time
from pathlib import Path

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = 'your-secret-key-here'
socketio = SocketIO(app, cors_allowed_origins="*")

# Create directories
Path("static/audio").mkdir(parents=True, exist_ok=True)
Path("templates").mkdir(parents=True, exist_ok=True)

# Global state
class AudioManager:
    def __init__(self):
        self.sequences = []
        self.current_index = 0
        self.is_playing = False
        self.is_paused = False
        self.audio_queue = queue.Queue()
        self.current_audio_file = None
        self.next_audio_file = None
        self.processing_thread = None
        
    def load_sequences(self, sequences):
        self.sequences = sequences
        self.current_index = 0
        self.preprocess_next()
        
    def preprocess_next(self):
        """Preprocess the next audio in background"""
        if self.current_index < len(self.sequences):
            next_index = self.current_index
            if next_index < len(self.sequences):
                threading.Thread(target=self._convert_to_audio, args=(next_index,)).start()
    
    def _convert_to_audio(self, index):
        """Convert text to audio file"""
        if index >= len(self.sequences):
            return
            
        text = self.sequences[index]['text']
        filename = f"static/audio/audio_{index}.mp3"
        
        try:
            tts = gTTS(text=text, lang='en')
            tts.save(filename)
            
            if index == self.current_index:
                self.current_audio_file = filename
            elif index == self.current_index + 1:
                self.next_audio_file = filename
                
            print(f"Converted sequence {index} to audio: {filename}")
        except Exception as e:
            print(f"Error converting text to audio: {e}")
    
    def play_next(self):
        """Play the next sequence"""
        if self.current_index < len(self.sequences):
            # Current audio is ready
            if self.current_audio_file:
                audio_url = f"/{self.current_audio_file}"
                socketio.emit('play_audio', {
                    'audio_url': audio_url,
                    'sequence_index': self.current_index
                })
                self.is_playing = True
                self.is_paused = False
                
                # Move to next and preprocess
                self.current_index += 1
                self.current_audio_file = self.next_audio_file
                self.next_audio_file = None
                
                # Preprocess the next one
                if self.current_index < len(self.sequences):
                    threading.Thread(target=self._convert_to_audio, args=(self.current_index,)).start()
                
                return True
        return False
    
    def skip_next(self):
        """Skip to the next sequence"""
        if self.current_index < len(self.sequences) - 1:
            self.current_index += 1
            self.current_audio_file = None
            self.next_audio_file = None
            self.preprocess_next()
            return True
        return False
    
    def pause(self):
        """Pause current playback"""
        self.is_paused = True
        socketio.emit('pause_audio')
        
    def resume(self):
        """Resume playback"""
        self.is_paused = False
        socketio.emit('resume_audio')
    
    def update_sequence(self, index, text):
        """Update a sequence text"""
        if 0 <= index < len(self.sequences):
            self.sequences[index]['text'] = text
            # If updating current or next, reprocess
            if index == self.current_index or index == self.current_index + 1:
                threading.Thread(target=self._convert_to_audio, args=(index,)).start()

audio_manager = AudioManager()

@app.route('/')
def index():
    """Visualizer page"""
    return render_template('visualizer.html')

@app.route('/admin')
def admin():
    """Admin control page"""
    return render_template('admin.html')

@app.route('/upload_json', methods=['POST'])
def upload_json():
    """Handle JSON file upload"""
    try:
        file = request.files['file']
        content = file.read()
        data = json.loads(content)
        
        # Expected format: {"sequences": [{"text": "..."}, ...]}
        sequences = data.get('sequences', [])
        audio_manager.load_sequences(sequences)
        
        return jsonify({
            'success': True,
            'sequences': sequences,
            'message': f'Loaded {len(sequences)} sequences'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/update_sequence', methods=['POST'])
def update_sequence():
    """Update a specific sequence"""
    try:
        data = request.json
        index = data['index']
        text = data['text']
        audio_manager.update_sequence(index, text)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/play_next', methods=['POST'])
def play_next():
    """Trigger playing the next audio"""
    success = audio_manager.play_next()
    return jsonify({'success': success})

@app.route('/skip_next', methods=['POST'])
def skip_next():
    """Skip to the next sequence"""
    success = audio_manager.skip_next()
    return jsonify({'success': success})

@app.route('/pause', methods=['POST'])
def pause():
    """Pause playback"""
    audio_manager.pause()
    return jsonify({'success': True})

@app.route('/resume', methods=['POST'])
def resume():
    """Resume playback"""
    audio_manager.resume()
    return jsonify({'success': True})

@app.route('/status')
def status():
    """Get current status"""
    return jsonify({
        'current_index': audio_manager.current_index,
        'total_sequences': len(audio_manager.sequences),
        'is_playing': audio_manager.is_playing,
        'is_paused': audio_manager.is_paused,
        'sequences': audio_manager.sequences
    })

@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)