<script lang="ts">
  interface Props {
    status: "connecting" | "connected" | "reconnecting" | "disconnected";
  }

  let { status }: Props = $props();

  const labels: Record<Props["status"], string> = {
    connecting: "Connecting…",
    connected: "Live",
    reconnecting: "Reconnecting…",
    disconnected: "Offline",
  };
</script>

<span class="stream-indicator {status}">
  <span class="dot"></span>
  <span class="label">{labels[status]}</span>
</span>

<style>
  .stream-indicator {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 0.75rem;
    padding: 4px 12px;
    border-radius: 12px;
    background: var(--card);
    border: 1px solid var(--border);
    transition: all var(--transition);
  }

  .stream-indicator .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--dim);
    transition: background var(--transition);
  }

  .stream-indicator.connected {
    border-color: var(--green);
    color: var(--green);
  }

  .stream-indicator.connected .dot {
    background: var(--green);
    box-shadow: 0 0 6px var(--green);
  }

  .stream-indicator.reconnecting,
  .stream-indicator.connecting {
    border-color: var(--amber);
    color: var(--amber);
  }

  .stream-indicator.reconnecting .dot,
  .stream-indicator.connecting .dot {
    background: var(--amber);
    animation: pulse 1.5s infinite;
  }

  .stream-indicator.disconnected {
    border-color: var(--red);
    color: var(--red);
  }

  .stream-indicator.disconnected .dot {
    background: var(--red);
  }

  @keyframes pulse {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.3;
    }
  }
</style>
