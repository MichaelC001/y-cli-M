/**
 * Y-CLI Chat Backup Worker
 * 
 * This worker merges chat data from KV into R2 storage.
 * Deploy this worker with a scheduled trigger (e.g., daily) to ensure
 * your chat data is regularly backed up.
 * 
 * Required bindings:
 * - KV namespace: CHAT_KV (bind to your chat KV namespace)
 * - R2 bucket: CHAT_R2 (bind to your chat backup R2 bucket)
 */

export default {
  // Scheduled handler that runs on the defined cron schedule
  async scheduled(event, env, ctx) {
    return await handleBackup(event, env, ctx);
  },
  
  // HTTP handler for manual triggering via fetch
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    
    // Simple authentication using a secret path
    if (url.pathname !== '/backup' || request.method !== 'POST') {
      return new Response('Not found', { status: 404 });
    }
    
    try {
      await handleBackup(null, env, ctx);
      return new Response('Backup completed successfully', { status: 200 });
    } catch (error) {
      return new Response(`Backup failed: ${error.message}`, { status: 500 });
    }
  }
};

/**
 * Main backup handler function
 */
async function handleBackup(event, env, ctx) {
  console.log('Starting chat merge process');
  
  try {
    // Get all chats from KV
    let kvChats = [];
    const kvData = await env.CHAT_KV.get('chats');
    if (kvData) {
      // Parse JSONL format (each line is a JSON object)
      kvChats = kvData
        .split('\n')
        .filter(line => line.trim())
        .map(line => JSON.parse(line));
    }
    console.log(`Retrieved ${kvChats.length} chats from KV`);
    
    // Get existing chats from R2
    let r2Chats = [];
    try {
      const r2Object = await env.CHAT_R2.get('chat.jsonl');
      if (r2Object) {
        const r2Data = await r2Object.text();
        // Parse JSONL format (each line is a JSON object)
        r2Chats = r2Data
          .split('\n')
          .filter(line => line.trim())
          .map(line => JSON.parse(line));
        console.log(`Retrieved ${r2Chats.length} chats from R2`);
      } else {
        console.log('No existing chats in R2');
      }
    } catch (error) {
      console.warn(`Error reading from R2: ${error.message}`);
      console.log('Continuing with empty R2 chat list');
    }
    
    // If no chats in KV and R2 exists, nothing to do
    if (kvChats.length === 0 && r2Chats.length === 0) {
      console.log('No chats to merge');
      return;
    }
    
    // Merge chats from KV and R2, with KV taking precedence for duplicates
    const mergedChats = mergeChats(r2Chats, kvChats);
    console.log(`Merged into ${mergedChats.length} total chats`);
    
    // Format as JSONL for R2 storage
    const jsonlData = mergedChats.map(chat => JSON.stringify(chat)).join('\n');
    
    // Store in R2
    await env.CHAT_R2.put('chat.jsonl', jsonlData);
    console.log('Merged chats saved to R2: chat.jsonl');
    
    // Calculate SHA-256 checksum of the content
    const checksum = await calculateChecksum(jsonlData);
    
    // Store checksum in both R2 and KV for faster access
    await env.CHAT_R2.put('chat_ver', checksum);
    await env.CHAT_KV.put('chat_ver', checksum);
    console.log('Checksum saved to R2 and KV: chat_ver');
    
    // Clear KV store since data is now in R2
    // Only clear if we have successfully written to R2
    if (kvChats.length > 0) {
      // Set to empty string to match JSONL format (not an empty JSON array)
      await env.CHAT_KV.put('chats', '');
      console.log('Cleared KV store after successful merge');
    }
    
    console.log('Chat merge completed successfully');
  } catch (error) {
    console.error(`Merge failed: ${error.message}`);
    throw error;
  }
}

/**
 * Calculate SHA-256 checksum of content
 * @param {string} content - Content to calculate checksum for
 * @returns {Promise<string>} - Promise resolving to SHA-256 checksum as hex string
 */
async function calculateChecksum(content) {
  // Use Web Crypto API to calculate SHA-256 hash
  const encoder = new TextEncoder();
  const data = encoder.encode(content);
  
  // Calculate hash
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  
  // Convert ArrayBuffer to hex string
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Merge chats from two sources, with source2 taking precedence for duplicates
 * @param {Array} source1 - First source of chats (e.g., from R2)
 * @param {Array} source2 - Second source of chats (e.g., from KV)
 * @returns {Array} - Merged array of chats
 */
function mergeChats(source1, source2) {
  // Create a map of chats by ID for easy lookup
  const chatMap = new Map();
  
  // Add all chats from source1 (e.g., R2)
  for (const chat of source1) {
    if (chat && chat.id) {
      chatMap.set(chat.id, chat);
    }
  }
  
  // Add or override with chats from source2 (e.g., KV)
  for (const chat of source2) {
    if (chat && chat.id) {
      chatMap.set(chat.id, chat);
    }
  }
  
  // Convert map back to array
  return Array.from(chatMap.values());
}
