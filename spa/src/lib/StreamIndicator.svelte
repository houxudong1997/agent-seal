<script lang="ts">
  interface Props {
    status: "connecting" | "connected" | "reconnecting" | "disconnected";
  }

  let { status }: Props = $props();

  const labels: Record<Props["status"], string> = {
    connecting: "Connecting",
    connected: "Live",
    reconnecting: "Reconnecting",
    disconnected: "Offline",
  };
</script>

<span class="stream-indicator" class:connected={status === "connected"} class:connecting={status === "connecting" || status === "reconnecting"} class:disconnected={status === "disconnected"}>
  <span class="dot"></span>
  <span class="label">{labels[status]}</span>
</span>

<style>
  .stream-indicator {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 0.7rem;
    font-weight: 500;
    padding: 4px 12px;
    border-radius: 20px;
    background: var(--glass-alt);
    border: 1px solid var(--glass-border);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    transition: all var(--transition);
    color: var(--dim);
  }

  .stream-indicator .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--dim);
    transition: all var(--transition);
  }

  .stream-indicator.connected {
    border-color: rgba(52, 211, 153, 0.2);
    color: var(--green);
  }

  .stream-indicator.connected .dot {
    background: var(--green);
    box-shadow: 0 0 6px var(--green);
  }

  .stream-indicator.connecting {
    border-color: rgba(245, 158, 11, 0.2);
    color: var(--amber-text);
  }

  .stream-indicator.connecting .dot {
    background: var(--amber);
    animation: pulse 1.5s infinite;
  }

  .stream-indicator.disconnected {
    border-color: rgba(248, 113, 113, 0.15);
    color: var(--red);
  }

  .stream-indicator.disconnected .dot {
    background: var(--red);
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }
</style>
