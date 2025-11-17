import { fork } from 'child_process';
import { nanoid } from 'nanoid';
import EventEmitter from 'events';
import { extractMeetingCode } from '../services/utils/utils.js';

export class MeetingManager extends EventEmitter {
  static instance = null;
  
  constructor() {
    super();
    this.activeMeetings = new Map();
    console.log('🏗️ [Manager] MeetingManager instance created');
  }
  
  static getInstance() {
    if (!MeetingManager.instance) {
      MeetingManager.instance = new MeetingManager();
    }

    return MeetingManager.instance;
  }
  
  /**
   * Create a new meeting and spawn child process
   */
  async createMeeting(meetingUrl, adminUser = {}, asGuest = false) {

    const meetingId = extractMeetingCode(meetingUrl);

    if (!meetingId) throw new Error('MeetingId NOT GENERATED : Invalid meeting URL or code');
    
    console.log(`\n${'='.repeat(80)}`);
    console.log(`🚀 [Manager] Creating NEW meeting`);
    console.log(`   Meeting ID: ${meetingId}`);
    console.log(`   Meeting URL: ${meetingUrl}`);
    console.log(`   Admin User: ${JSON.stringify(adminUser)}`);
    console.log(`   As Guest: ${asGuest}`);
    console.log(`${'='.repeat(80)}\n`);

    const childEnv = {
      ...process.env,
      MEETING_ID: meetingId,
      MEETING_URL: meetingUrl,
      AS_GUEST: asGuest.toString(),
    };

    if (adminUser) {
      if (adminUser.email) {
        childEnv.USER_EMAIL = adminUser.email;
      } 
      if (adminUser.name) {
        childEnv.USER_NAME = adminUser.name;
      }
    }

    if (this.activeMeetings.has(meetingId)) {
      throw new Error(`Meeting ${meetingId} is already active`);
    }
    
    const childProcess = fork('./services/meetingProcess.js', {
      env: childEnv,
      stdio: ['pipe', 'pipe', 'pipe', 'ipc']
    });
    
    const meetingData = {
      process: childProcess,
      meetingUrl,
      status: 'initializing',
      startTime: Date.now(),
      adminUser,
      pendingCommands: new Map(),
      pid: childProcess.pid
    };
    
    this.activeMeetings.set(meetingId, meetingData);
    console.log(`✅ [Manager] Meeting ${meetingId} registered. Process PID: ${childProcess.pid}`);
    console.log(`   Active meetings count: ${this.activeMeetings.size}`);
    
    this.setupProcessHandlers(meetingId, childProcess);
    
    try {
      await this.waitForStatus(meetingId, 'active', 60000);
      console.log(`✅ [Manager] Meeting ${meetingId} is now ACTIVE\n`);
      return { meetingId };
    } catch (error) {
      console.error(`❌ [Manager] Meeting ${meetingId} failed to initialize:`, error.message);
      this.cleanupMeeting(meetingId);
      throw error;
    }
  }
  
  /**
   * Send command to child process and optionally wait for response
   */
  async sendCommand(meetingId, command, data = null, timeout = 5000) {
    console.log(`\n${'─'.repeat(80)}`);
    console.log(`📤 [Manager] Sending command to meeting ${meetingId}`);
    console.log(`   Command: ${command}`);
    console.log(`   Data:`, data);
    
    const meeting = this.activeMeetings.get(meetingId);
    
    if (!meeting) {
      console.error(`❌ [Manager] Meeting ${meetingId} NOT FOUND in active meetings`);
      console.log(`   Available meetings:`, Array.from(this.activeMeetings.keys()));
      throw new Error(`Meeting ${meetingId} not found`);
    }
    
    console.log(`   ✓ Meeting found. Status: ${meeting.status}, PID: ${meeting.pid}`);
    
    if (meeting.process.killed) {
      console.error(`❌ [Manager] Meeting ${meetingId} process is KILLED`);
      throw new Error(`Meeting ${meetingId} process is not running`);
    }
    
    const commandId = nanoid();
    
    const message = {
      type: command,
      data,
      commandId,
      timestamp: Date.now()
    };
    
    console.log(`   📨 Sending IPC message to child process (PID: ${meeting.pid})`);
    console.log(`   CommandID: ${commandId}`);
    
    meeting.process.send(message);
    console.log(`   ✅ Message sent via IPC`);
    console.log(`${'─'.repeat(80)}\n`);
    
    // If timeout specified, wait for response
    if (timeout > 0) {
      return new Promise((resolve, reject) => {
        const timeoutHandle = setTimeout(() => {
          console.error(`⏰ [Manager] Command ${command} TIMED OUT for meeting ${meetingId} (commandId: ${commandId})`);
          meeting.pendingCommands.delete(commandId);
          reject(new Error(`Command ${command} timed out after ${timeout}ms`));
        }, timeout);
        
        meeting.pendingCommands.set(commandId, {
          resolve: (result) => {
            console.log(`✅ [Manager] Command ${command} RESOLVED for meeting ${meetingId} (commandId: ${commandId})`);
            clearTimeout(timeoutHandle);
            meeting.pendingCommands.delete(commandId);
            resolve(result);
          },
          reject: (error) => {
            console.error(`❌ [Manager] Command ${command} REJECTED for meeting ${meetingId} (commandId: ${commandId}):`, error);
            clearTimeout(timeoutHandle);
            meeting.pendingCommands.delete(commandId);
            reject(error);
          }
        });
        
        console.log(`⏳ [Manager] Waiting for response... (timeout: ${timeout}ms, commandId: ${commandId})`);
      });
    }
  }
  
  /**
   * Setup event handlers for child process
   */
  setupProcessHandlers(meetingId, childProcess) {
    console.log(`🔧 [Manager] Setting up handlers for meeting ${meetingId}`);
    
    // Handle messages from child
    childProcess.on('message', (msg) => {
      this.handleChildMessage(meetingId, msg);
    });
    
    // Handle stdout (for logging)
    childProcess.stdout.on('data', (data) => {
      console.log(`📋 [stdout-${meetingId}] ${data.toString().trim()}`);
    });
    
    // Handle stderr
    childProcess.stderr.on('data', (data) => {
      console.error(`❌ [stderr-${meetingId}] ${data.toString().trim()}`);
    });
    
    // Handle process errors
    childProcess.on('error', (error) => {
      console.error(`❌ [Manager] Process error for meeting ${meetingId}:`, error);
      const meeting = this.activeMeetings.get(meetingId);
      if (meeting) {
        meeting.status = 'error';
      }
      this.emit('meetingError', { meetingId, error });
    });
    
    // Handle process exit
    childProcess.on('exit', (code, signal) => {
      console.log(`🚪 [Manager] Process EXITED for meeting ${meetingId} (code: ${code}, signal: ${signal})`);
      this.cleanupMeeting(meetingId);
      this.emit('meetingEnded', { meetingId, code, signal });
    });
  }
  
  /**
   * Handle messages from child process
   */
  handleChildMessage(meetingId, msg) {
    const meeting = this.activeMeetings.get(meetingId);
    
    if (!meeting) {
      console.warn(`⚠️ [Manager] Received message from unknown meeting ${meetingId}`);
      return;
    }
    
    console.log(`📨 [Manager] ⬆️ RECEIVED message from child ${meetingId}: "${msg.type}"${msg.commandId ? ` (commandId: ${msg.commandId})` : ''}`);
    
    // Handle command responses
    if (msg.commandId && meeting.pendingCommands.has(msg.commandId)) {
      console.log(`   🎯 Matched pending command: ${msg.commandId}`);
      const pending = meeting.pendingCommands.get(msg.commandId);
      
      if (msg.type === 'COMMAND_SUCCESS') {
        console.log(`   ✅ Command succeeded`);
        pending.resolve(msg.data);
      } else if (msg.type === 'COMMAND_ERROR') {
        console.log(`   ❌ Command failed: ${msg.error}`);
        pending.reject(new Error(msg.error));
      }

      return;
    }
    
    // Handle status updates
    switch (msg.type) {
      case 'JOINED':
        console.log(`✅ [Manager] Meeting ${meetingId} JOINED successfully`);
        meeting.status = 'active';
        this.emit('meetingJoined', { meetingId });
        break;
        
      case 'LEFT':
        console.log(`👋 [Manager] Meeting ${meetingId} LEFT`);
        meeting.status = 'completed';
        this.emit('meetingLeft', { meetingId });
        break;
        
      case 'ERROR':
        console.error(`❌ [Manager] Error from meeting ${meetingId}:`, msg.error);
        meeting.status = 'error';
        this.emit('meetingError', { meetingId, error: msg.error });
        break;
        
      case 'PARTICIPANT_COUNT':
        meeting.participantCount = msg.count;
        this.emit('participantCountChanged', { meetingId, count: msg.count });
        break;
        
      case 'RECORDING_STARTED':
        console.log(`🎙️ [Manager] Meeting ${meetingId} recording STARTED`);
        meeting.status = 'recording';
        this.emit('recordingStarted', { meetingId });
        break;
        
      case 'RECORDING_STOPPED':
        console.log(`⏹️ [Manager] Meeting ${meetingId} recording STOPPED (duration: ${msg.duration}ms)`);
        meeting.status = 'active';
        this.emit('recordingStopped', { meetingId, duration: msg.duration });
        break;
        
      case 'CHAT_MESSAGE':
        this.emit('chatMessage', { meetingId, message: msg.data });
        break;
    }
  }
  
  /**
   * Wait for meeting to reach specific status
   */
  waitForStatus(meetingId, targetStatus, timeout) {
    console.log(`⏳ [Manager] Waiting for meeting ${meetingId} to reach status: ${targetStatus}`);
    
    return new Promise((resolve, reject) => {
      const meeting = this.activeMeetings.get(meetingId);
      if (!meeting) {
        return reject(new Error(`Meeting ${meetingId} not found`));
      }
      
      if (meeting.status === targetStatus) {
        console.log(`   ✅ Already at target status`);
        return resolve();
      }
      
      const checkInterval = setInterval(() => {
        const current = this.activeMeetings.get(meetingId);
        if (!current) {
          clearInterval(checkInterval);
          clearTimeout(timeoutHandle);
          reject(new Error(`Meeting ${meetingId} was removed`));
        } else if (current.status === targetStatus) {
          clearInterval(checkInterval);
          clearTimeout(timeoutHandle);
          console.log(`   ✅ Reached target status: ${targetStatus}`);
          resolve();
        } else if (current.status === 'error') {
          clearInterval(checkInterval);
          clearTimeout(timeoutHandle);
          reject(new Error(`Meeting ${meetingId} encountered an error`));
        }
      }, 500);
      
      const timeoutHandle = setTimeout(() => {
        clearInterval(checkInterval);
        reject(new Error(`Timeout waiting for status ${targetStatus}`));
      }, timeout);
    });
  }
  
  /**
   * Get meeting status
   */
  getMeetingStatus(meetingId) {
    const meeting = this.activeMeetings.get(meetingId);
    if (!meeting) return null;
    
    return {
      meetingId,
      status: meeting.status,
      meetingUrl: meeting.meetingUrl,
      uptime: Date.now() - meeting.startTime,
      participantCount: meeting.participantCount || 0,
      pid: meeting.pid
    };
  }
  
  /**
   * Get all meetings
   */
  getAllMeetings() {
    console.log(`📊 [Manager] Getting all meetings. Count: ${this.activeMeetings.size}`);
    
    return Array.from(this.activeMeetings.entries()).map(([id, data]) => ({
      meetingId: id,
      status: data.status,
      meetingUrl: data.meetingUrl,
      uptime: Date.now() - data.startTime,
      participantCount: data.participantCount || 0,
      pid: data.pid
    }));
  }
  
  /**
   * Cleanup meeting resources
   */
  cleanupMeeting(meetingId) {
    const meeting = this.activeMeetings.get(meetingId);
    if (!meeting) return;
    
    console.log(`🧹 [Manager] Cleaning up meeting ${meetingId}`);
    
    // Reject all pending commands
    for (const [cmdId, pending] of meeting.pendingCommands) {
      console.log(`   ❌ Rejecting pending command: ${cmdId}`);
      pending.reject(new Error('Meeting is being cleaned up'));
    }
    meeting.pendingCommands.clear();
    
    // Kill process if still running
    if (!meeting.process.killed) {
      console.log(`   🔪 Killing process PID: ${meeting.pid}`);
      meeting.process.kill('SIGTERM');
      
      setTimeout(() => {
        if (!meeting.process.killed) {
          console.warn(`   ⚠️ Force killing meeting ${meetingId}`);
          meeting.process.kill('SIGKILL');
        }
      }, 5000);
    }
    
    this.activeMeetings.delete(meetingId);
    console.log(`   ✅ Meeting ${meetingId} removed. Active meetings: ${this.activeMeetings.size}\n`);
  }
  
  /**
   * Shutdown all meetings gracefully
   */
  async shutdown() {
    console.log('🛑 [Manager] Shutting down ALL meetings...');
    
    const shutdownPromises = [];
    
    for (const [meetingId, meeting] of this.activeMeetings) {
      shutdownPromises.push(
        this.sendCommand(meetingId, 'LEAVE', null, 10000)
          .catch(err => console.error(`Error shutting down ${meetingId}:`, err))
      );
    }
    
    await Promise.allSettled(shutdownPromises);
    
    setTimeout(() => {
      for (const meetingId of this.activeMeetings.keys()) {
        this.cleanupMeeting(meetingId);
      }
    }, 15000);
  }
}