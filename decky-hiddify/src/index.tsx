import React, { useState, useEffect, Component, ReactNode } from "react";
import {
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  staticClasses,
  Spinner,
} from "@decky/ui";
import {
  addEventListener,
  removeEventListener,
  callable,
  definePlugin,
  toaster,
} from "@decky/api";

// ── Error boundary ──────────────────────────────────────────────────────────
class ErrBoundary extends Component<{ children: ReactNode }, { err: string | null }> {
  state = { err: null };
  static getDerivedStateFromError(e: any) { return { err: String(e) }; }
  render() {
    if (this.state.err) {
      return (
        <PanelSection>
          <PanelSectionRow>
            <div style={{ fontSize: 11, color: "#f87171", padding: 8 }}>
              ⚠ Render error:<br />{this.state.err}
            </div>
          </PanelSectionRow>
        </PanelSection>
      );
    }
    return this.props.children;
  }
}

// ── Icons ───────────────────────────────────────────────────────────────────
const ShieldIcon = ({ color = "currentColor" }: { color?: string }) => (
  <svg viewBox="0 0 24 24" width="1em" height="1em" fill={color}>
    <path d="M12 2L4 5v6c0 5.25 3.4 10.15 8 11.38C16.6 21.15 20 16.25 20 11V5L12 2z"/>
  </svg>
);

// ── Callables ───────────────────────────────────────────────────────────────
const getStatus        = callable<[], {
  connected: boolean; running: boolean; vpn_ip: string; install_state: string; active_profile: string;
}>("get_status");
const startVpn         = callable<[], { success: boolean; message: string }>("start_vpn");
const stopVpn          = callable<[], { success: boolean; message: string }>("stop_vpn");
const getInstallStatus = callable<[], {
  state: string; message: string; cli_exists: boolean;
}>("get_install_status");
const repair           = callable<[], { success: boolean; message: string }>("repair");
const getLogs          = callable<[], string>("get_logs");
const getProfiles      = callable<[], Array<{ id: string; name: string; active: boolean }>>("get_profiles");
const switchProfile    = callable<[string], { success: boolean; message: string }>("switch_profile");

interface VpnStatus {
  connected: boolean; running: boolean; vpn_ip: string; install_state: string; active_profile: string;
}
interface Profile { id: string; name: string; active: boolean; }

// ── VPN panel ───────────────────────────────────────────────────────────────
function VpnPanel() {
  const [status, setStatus]       = useState<VpnStatus>({
    connected: false, running: false, vpn_ip: "", install_state: "ready", active_profile: "",
  });
  const [loading, setLoading]     = useState(false);
  const [profiles, setProfiles]   = useState<Profile[]>([]);
  const [switching, setSwitching] = useState(false);
  const [showLogs, setShowLogs]   = useState(false);
  const [logs, setLogs]           = useState("");

  const fetchStatus = async () => {
    try { setStatus(await getStatus()); } catch {}
  };

  const fetchProfiles = async () => {
    try { setProfiles(await getProfiles()); } catch {}
  };

  useEffect(() => {
    fetchStatus();
    fetchProfiles();

    const listener = addEventListener<[VpnStatus & { dropped?: boolean }]>("vpn_status_changed", (s) => {
      if ((s as any).dropped) {
        toaster.toast({ title: "Hiddify VPN", body: "VPN disconnected — tap to reconnect", duration: 5000 });
      }
      setStatus(prev => ({ ...prev, ...s }));
    });
    const iv = setInterval(fetchStatus, 5000);
    return () => { removeEventListener("vpn_status_changed", listener); clearInterval(iv); };
  }, []);

  const handleToggle = async () => {
    if (loading) return;
    setLoading(true);
    const wasOn = status.connected;
    try {
      const result = wasOn ? await stopVpn() : await startVpn();
      if (!result.success) {
        toaster.toast({ title: "VPN Error", body: result.message, duration: 5000 });
        await fetchStatus();
        return;
      }
      for (let i = 0; i < 18; i++) {
        await new Promise(r => setTimeout(r, 1000));
        await fetchStatus();
        const s = await getStatus();
        setStatus(s);
        if (!wasOn && s.connected) break;
        if (wasOn && !s.connected && !s.running) break;
      }
      const final = await getStatus();
      setStatus(final);
      toaster.toast({ title: "Hiddify VPN", body: final.connected ? "VPN ON" : "VPN OFF", duration: 3000 });
    } catch (e: any) {
      toaster.toast({ title: "Error", body: String(e), duration: 5000 });
      await fetchStatus();
    } finally {
      setLoading(false);
    }
  };

  const handleSwitch = async (id: string) => {
    setSwitching(true);
    try {
      const r = await switchProfile(id);
      if (r.success) {
        await fetchProfiles();
        await fetchStatus();
        toaster.toast({ title: "Hiddify VPN", body: r.message, duration: 3000 });
      } else {
        toaster.toast({ title: "Profile Error", body: r.message, duration: 5000 });
      }
    } catch (e: any) {
      toaster.toast({ title: "Error", body: String(e), duration: 5000 });
    } finally {
      setSwitching(false);
    }
  };

  const isOn = status.connected;

  // Status dot color
  const dotColor = status.connected ? "#4ade80" : status.running ? "#facc15" : "#f87171";
  const statusText = loading
    ? (isOn ? "Disconnecting…" : "Connecting…")
    : status.connected
    ? (status.vpn_ip ? `Connected · ${status.vpn_ip}` : "Connected")
    : status.running ? "Connecting…" : "Disconnected";

  return (
    <div>
      <PanelSection>
        {/* Toggle row */}
        <PanelSectionRow>
          <ButtonItem onClick={handleToggle} disabled={loading} layout="below">
            <div style={{ display: "flex", alignItems: "center", gap: 10, width: "100%" }}>
              {/* Dot indicator */}
              <div style={{
                width: 10, height: 10, borderRadius: "50%", flexShrink: 0,
                background: dotColor, boxShadow: `0 0 6px ${dotColor}`,
              }} />
              {/* Label + description */}
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: "bold", color: dotColor }}>
                  {isOn ? "VPN ON" : "VPN OFF"}
                </div>
                <div style={{ fontSize: 11, opacity: 0.7 }}>{statusText}</div>
              </div>
              {/* Loading spinner */}
              {loading && <Spinner style={{ width: 16, height: 16 }} />}
            </div>
          </ButtonItem>
        </PanelSectionRow>

        {/* Profile selector */}
        {profiles.length > 1 && (
          <PanelSectionRow>
            <div style={{ width: "100%", paddingTop: 4 }}>
              <div style={{ fontSize: 11, opacity: 0.5, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                {isOn ? "Stop VPN to change profile" : "Profile"}
              </div>
              {profiles.map(p => (
                <ButtonItem
                  key={p.id}
                  onClick={() => !isOn && !switching && !p.active && handleSwitch(p.id)}
                  disabled={isOn || switching || p.active}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <div style={{
                      width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
                      background: p.active ? "#4ade80" : "rgba(255,255,255,0.25)",
                    }} />
                    <span style={{ flex: 1 }}>{p.name}</span>
                    {p.active && (
                      <span style={{ fontSize: 10, color: "#4ade80" }}>active</span>
                    )}
                  </div>
                </ButtonItem>
              ))}
            </div>
          </PanelSectionRow>
        )}
      </PanelSection>

      {/* Logs */}
      <PanelSection title="Tools">
        <PanelSectionRow>
          <ButtonItem onClick={async () => {
            try { setLogs(await getLogs()); } catch (e: any) { setLogs(`Error: ${e}`); }
            setShowLogs(v => !v);
          }}>
            {showLogs ? "Hide logs" : "Show logs"}
          </ButtonItem>
        </PanelSectionRow>
        {showLogs && (
          <PanelSectionRow>
            <div style={{
              fontSize: 10, fontFamily: "monospace", whiteSpace: "pre-wrap",
              wordBreak: "break-all", maxHeight: 180, overflowY: "auto",
              background: "rgba(0,0,0,0.3)", padding: 8, borderRadius: 4,
            }}>
              {logs || "No logs"}
            </div>
          </PanelSectionRow>
        )}
      </PanelSection>
    </div>
  );
}

// ── Install / repair panel ──────────────────────────────────────────────────
function InstallPanel({ state, message, onDone }: { state: string; message: string; onDone: () => void }) {
  const [loading, setLoading] = useState(false);

  const handleRepair = async () => {
    setLoading(true);
    try {
      const r = await repair();
      toaster.toast({ title: "Hiddify", body: r.message, duration: 3000 });
      if (r.success) onDone();
    } catch (e: any) {
      toaster.toast({ title: "Error", body: String(e), duration: 5000 });
    }
    setLoading(false);
  };

  return (
    <PanelSection>
      <PanelSectionRow>
        <div style={{ fontSize: 13, color: "#facc15", fontWeight: "bold", marginBottom: 6 }}>
          {state === "needs_repair" ? "⚠ Repair required" : "🔧 Not installed"}
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={{ fontSize: 12, opacity: 0.8 }}>{message}</div>
      </PanelSectionRow>
      {state === "not_installed" && (
        <PanelSectionRow>
          <div style={{ fontSize: 11, opacity: 0.6, lineHeight: 1.8 }}>
            Open Konsole and run:<br />
            <code style={{ fontSize: 10, background: "rgba(0,0,0,0.3)", padding: "2px 6px", borderRadius: 2 }}>
              bash ~/Downloads/Hiddify-linux-x64.bin
            </code>
          </div>
        </PanelSectionRow>
      )}
      {state === "needs_repair" && (
        <PanelSectionRow>
          {loading
            ? <div style={{ display: "flex", alignItems: "center", gap: 8 }}><Spinner /><span>Repairing…</span></div>
            : <ButtonItem onClick={handleRepair}>🔧 Repair</ButtonItem>
          }
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

// ── Root ────────────────────────────────────────────────────────────────────
function Content() {
  const [installState, setInstallState]   = useState<string | null>(null);
  const [installMsg, setInstallMsg]       = useState("");
  const [checking, setChecking]           = useState(true);
  const [fetchError, setFetchError]       = useState<string | null>(null);

  const check = async () => {
    setChecking(true);
    setFetchError(null);
    try {
      const s = await getInstallStatus();
      setInstallState(s.state);
      setInstallMsg(s.message);
    } catch (e: any) {
      setFetchError(String(e));
    }
    setChecking(false);
  };

  useEffect(() => { check(); }, []);

  if (checking) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: 8 }}>
            <Spinner /><span style={{ fontSize: 12 }}>Checking…</span>
          </div>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  if (fetchError) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <div style={{ fontSize: 11, color: "#f87171", padding: 8, lineHeight: 1.5 }}>
            ⚠ Backend error:<br />{fetchError}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem onClick={check}>Retry</ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  if (installState === "ready") return <VpnPanel />;

  return (
    <InstallPanel
      state={installState ?? "not_installed"}
      message={installMsg}
      onDone={check}
    />
  );
}

export default definePlugin(() => ({
  name: "Hiddify VPN",
  title: (
    <div className={staticClasses.Title} style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <ShieldIcon color="#4ade80" />
      Hiddify VPN
    </div>
  ),
  content: (
    <ErrBoundary>
      <Content />
    </ErrBoundary>
  ),
  icon: <ShieldIcon />,
  onDismount() {},
}));
