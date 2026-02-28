# PWN Configuration

This directory contains personal configuration files (git-ignored).

## notifications.json

Configure how you receive notifications when tasks complete.

### Channels

#### Desktop (default)
Native OS notifications. Works out of the box on Windows, macOS, and Linux.

```json
{
  "channels": {
    "desktop": {
      "enabled": true
    }
  }
}
```

#### ntfy.sh
Free, open-source push notifications. Great for mobile alerts.

```json
{
  "channels": {
    "ntfy": {
      "enabled": true,
      "server": "https://ntfy.sh",
      "topic": "pwn-abc12345",
      "priority": "default"
    }
  }
}
```

**Setup:**
1. A unique topic is auto-generated during `pwn inject`
2. Subscribe to your topic:
   - Browser: `https://ntfy.sh/YOUR_TOPIC`
   - Mobile: Install ntfy app and subscribe to your topic
3. Enable: set `enabled: true`
4. Test: `pwn notify test ntfy`

**Privacy:** Topics are public by default. Your auto-generated topic uses a random ID making it hard to guess. For private topics, create an account at ntfy.sh or self-host.

#### Pushover (paid)
Premium push notification service with more features.

```json
{
  "channels": {
    "pushover": {
      "enabled": true,
      "userKey": "your-user-key",
      "apiToken": "your-api-token"
    }
  }
}
```

### Priority Levels

- `low` - Silent, no sound
- `default` - Normal notification
- `high` - Important, may bypass DND
- `urgent` - Critical, persistent alert

### Commands

```bash
pwn notify test              # Test default channel (desktop)
pwn notify test ntfy         # Test specific channel
pwn notify send "Message"    # Send custom notification
pwn notify config            # Show current configuration
```
