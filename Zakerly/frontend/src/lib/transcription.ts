import { pipeline, env } from '@huggingface/transformers';

// Configure transformers.js
env.allowLocalModels = false;
env.useBrowserCache = true;

let transcriber: any = null;

export const initializeTranscriber = async () => {
  if (!transcriber) {
    console.log('Initializing speech recognition model...');
    transcriber = await pipeline(
      'automatic-speech-recognition',
      'onnx-community/whisper-tiny.en',
      { device: 'webgpu' }
    );
    console.log('Speech recognition model initialized');
  }
  return transcriber;
};

export const transcribeAudio = async (audioFile: File): Promise<string> => {
  try {
    console.log('Starting transcription process...');
    
    // Initialize transcriber if not already done
    const model = await initializeTranscriber();
    
    // Convert file to array buffer
    const arrayBuffer = await audioFile.arrayBuffer();
    
    // Transcribe the audio
    console.log('Processing audio file...');
    const output = await model(arrayBuffer);
    
    console.log('Transcription completed:', output);
    return output.text || '';
  } catch (error) {
    console.error('Error during transcription:', error);
    throw new Error('Failed to transcribe audio. Please try again.');
  }
};

export const extractAudioFromVideo = async (videoFile: File): Promise<Blob> => {
  return new Promise((resolve, reject) => {
    const video = document.createElement('video');
    const canvas = document.createElement('canvas');
    const audioContext = new AudioContext();
    
    video.onloadedmetadata = async () => {
      try {
        // Create audio buffer from video
        const arrayBuffer = await videoFile.arrayBuffer();
        const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
        
        // Convert to WAV format
        const wavBuffer = audioBufferToWav(audioBuffer);
        const audioBlob = new Blob([wavBuffer], { type: 'audio/wav' });
        
        resolve(audioBlob);
      } catch (error) {
        reject(error);
      }
    };
    
    video.onerror = () => reject(new Error('Failed to load video file'));
    video.src = URL.createObjectURL(videoFile);
  });
};

// Helper function to convert AudioBuffer to WAV
function audioBufferToWav(buffer: AudioBuffer): ArrayBuffer {
  const length = buffer.length;
  const numberOfChannels = buffer.numberOfChannels;
  const sampleRate = buffer.sampleRate;
  const bytesPerSample = 2;
  const blockAlign = numberOfChannels * bytesPerSample;
  const byteRate = sampleRate * blockAlign;
  const dataSize = length * blockAlign;
  const bufferSize = 44 + dataSize;
  
  const arrayBuffer = new ArrayBuffer(bufferSize);
  const view = new DataView(arrayBuffer);
  
  // WAV header
  const writeString = (offset: number, string: string) => {
    for (let i = 0; i < string.length; i++) {
      view.setUint8(offset + i, string.charCodeAt(i));
    }
  };
  
  writeString(0, 'RIFF');
  view.setUint32(4, bufferSize - 8, true);
  writeString(8, 'WAVE');
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, numberOfChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bytesPerSample * 8, true);
  writeString(36, 'data');
  view.setUint32(40, dataSize, true);
  
  // Convert audio data
  let offset = 44;
  for (let i = 0; i < length; i++) {
    for (let channel = 0; channel < numberOfChannels; channel++) {
      const sample = Math.max(-1, Math.min(1, buffer.getChannelData(channel)[i]));
      view.setInt16(offset, sample * 0x7fff, true);
      offset += 2;
    }
  }
  
  return arrayBuffer;
}