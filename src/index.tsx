import { callable, definePlugin } from "@decky/api";
import { ButtonItem, PanelSection, PanelSectionRow, SliderField, staticClasses } from "@decky/ui";
import { useEffect, useState } from "react";
import { FaFan } from "react-icons/fa";
import { version } from "../package.json";

type Point = [number, number];
type Reading = { temperature: number | null; rpm: number | null; target: number | null; active: boolean; error: string | null; releasing: boolean; enabled: boolean };
type Status = Reading & {
  available: boolean; reason: string | null; points: Point[]; minRpm: number; maxRpm: number;
};
const status = callable<[], Status>("get_state");
const reading = callable<[], Reading>("get_telemetry");
const apply = callable<[Point[]], Status>("apply_curve");
const restore = callable<[], Status>("restore_curve");

function projected(points: Point[], state: Status): Point[] {
  const floor = state.minRpm / state.maxRpm * 100;
  const temperatures = new Set([10, 100, ...points.map(([t]) => t)]);
  for (let i = 1; i < points.length; i++) {
    const [ta, pa] = points[i - 1];
    const [tb, pb] = points[i];
    if (pa < floor && pb > floor) {
      temperatures.add(ta + (tb - ta) * (floor - pa) / (pb - pa));
    }
  }
  const duty = (temp: number) => {
    if (temp <= points[0][0]) return points[0][1];
    for (let i = 1; i < points.length; i++) {
      const [ta, pa] = points[i - 1];
      const [tb, pb] = points[i];
      if (temp <= tb) return pa + (pb - pa) * (temp - ta) / (tb - ta);
    }
    return points[points.length - 1][1];
  };
  const zeroPoints = points.filter(([, p]) => p === 0);
  const lastZero = zeroPoints[zeroPoints.length - 1]?.[0];
  const hasPositive = points.some(([, p]) => p > 0);
  return [...temperatures].sort((a, b) => a - b).flatMap((t): Point[] => {
    const percent = duty(t);
    if (percent > 0) return [[t, Math.max(floor, percent)]];
    if (t === lastZero && hasPositive) return [[t, 0], [t, floor]];
    return [[t, 0]];
  });
}

function Chart({ points, preview }: { points: Point[]; preview: Point[] }) {
  const x = (t: number) => 28 + (t - 10) * 2.58;
  const y = (p: number) => 108 - p * .94;
  const line = (ps: Point[]) => ps.map(([t, p]) => `${x(t)},${y(p)}`).join(" ");
  return <svg viewBox="0 0 286 130" role="img" aria-label="温度与风扇百分比曲线" style={{ width: "100%", display: "block" }}>
    {[0, 50, 100].map(p => <g key={p}>
      <line x1={28} x2={260} y1={y(p)} y2={y(p)} stroke="#526174" />
      <text x={24} y={y(p)+3} fill="#c3cfda" textAnchor="end" fontSize="9">{p}%</text>
    </g>)}
    {[10, 40, 70, 100].map(t => <text key={t} x={x(t)} y={123} fill="#c3cfda" textAnchor="middle" fontSize="9">{t}°</text>)}
    <polyline points={line(points)} fill="none" stroke="#9aa9b9" strokeWidth="1.4" strokeDasharray="3 3" />
    <polyline points={line(preview)} fill="none" stroke="#6de4d2" strokeWidth="2.4" />
    {preview.map(([t,p], i) => <circle key={i} cx={x(t)} cy={y(p)} r="2.5" fill="#6de4d2" />)}
  </svg>;
}

function Content() {
  const [info, setInfo] = useState<Status>();
  const [sensor, setSensor] = useState<Reading>();
  const [points, setPoints] = useState<Point[]>([]);
  const [selected, select] = useState(0);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const show = (s: Status) => {
    setInfo(s); setSensor(s); setPoints(s.points);
    select(i => Math.min(i, s.points.length - 1));
  };
  useEffect(() => {
    let alive = true;
    status().then(s => { if (alive) show(s); }).catch(e => { if (alive) setMessage(String(e)); });
    let polling = false;
    const timer = setInterval(() => {
      if (polling) return;
      polling = true;
      reading().then(s => { if (alive) setSensor(s); }).catch(() => {}).finally(() => { polling = false; });
    }, 2500);
    return () => { alive = false; clearInterval(timer); };
  }, []);
  const act = async (action: () => Promise<Status>, success: string) => {
    setBusy(true); setMessage("");
    try { show(await action()); setMessage(success); }
    catch (e) { setMessage(String(e)); }
    finally { setBusy(false); }
  };
  const point = points[selected];
  const left = points[selected - 1];
  const right = points[selected + 1];
  const setPoint = (t: number, p: number) => setPoints(old => old.map((v, i) => i === selected ? [t,p] : v));
  const gap = points.slice(1).reduce((best, v, i) => v[0] - points[i][0] > (points[best+1]?.[0] ?? 0) - (points[best]?.[0] ?? 0) ? i : best, 0);
  const canAdd = points.length >= 2 && points.length < 10 && points[gap+1][0] - points[gap][0] >= 2;
  const add = () => {
    const [a,b] = [points[gap], points[gap + 1]];
    const temp = Math.floor((a[0] + b[0]) / 2);
    const percent = Math.round(a[1] + (b[1] - a[1]) * (temp - a[0]) / (b[0] - a[0]));
    setPoints([...points.slice(0, gap+1), [temp,percent], ...points.slice(gap+1)]);
    select(gap+1);
  };
  return <PanelSection title="Legion Go S 风扇曲线">
    <PanelSectionRow>
      <div>CPU {sensor?.temperature == null ? "—" : `${sensor.temperature} °C`} · 风扇 {sensor?.rpm == null ? "— RPM" : `${sensor.rpm} RPM`}</div>
      <div style={{ fontSize: 12, color: "#bdc8d5", marginTop: 5 }}>
        {sensor?.error || (info ? !info.available ? info.reason : sensor?.releasing ? "正在交回固件控制…" : sensor?.active ? `目标 ${sensor.target} RPM · 自定义曲线运行中` : sensor?.enabled ? "等待风扇驱动接管…" : "固件自动控制" : "正在读取设备…")}
      </div>
    </PanelSectionRow>
    {info && point && <>
      <PanelSectionRow>
        <Chart points={points} preview={projected(points, info)} />
        <div style={{fontSize:12, color:"#bdc8d5"}}>虚线为编辑曲线，实线为实际目标。<br/>0% 停转。转动时最低 {info.minRpm} RPM，100% 为 {info.maxRpm} RPM。</div>
      </PanelSectionRow>
      <PanelSectionRow><SliderField label="编辑节点" min={1} max={points.length} step={1} showValue value={selected + 1}
        disabled={busy} onChange={v => select(v - 1)} /></PanelSectionRow>
      <PanelSectionRow><SliderField label="温度" min={left ? left[0] + 1 : 10} max={right ? right[0] - 1 : 100} step={1}
        showValue valueSuffix=" °C" value={point[0]} disabled={busy} onChange={v => setPoint(v, point[1])} /></PanelSectionRow>
      <PanelSectionRow><SliderField label="目标转速百分比" min={left?.[1] ?? 0} max={right?.[1] ?? 100} step={1}
        showValue valueSuffix="%" value={point[1]} disabled={busy} onChange={v => setPoint(point[0], v)} /></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={busy || !canAdd} onClick={add}>添加节点</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={busy || points.length <= 2} onClick={() => {
        setPoints(points.filter((_, i) => i !== selected)); select(Math.max(0, selected - 1));
      }}>删除当前节点</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={busy || !info.available} onClick={() => void act(() => apply(points), "已保存并启用曲线。")}>保存并应用</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={busy || !(sensor?.enabled || sensor?.releasing)} onClick={() => void act(restore, "已交回固件自动控制。")}>恢复自动</ButtonItem></PanelSectionRow>
    </>}
    {message && <PanelSectionRow><div role="status">{message}</div></PanelSectionRow>}
    <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => void act(status, "已读取已保存的节点。")}>重新读取</ButtonItem></PanelSectionRow>
    <PanelSectionRow>
      <div style={{ fontSize: 12, color: "#bdc8d5", textAlign: "center" }}>版本 v{version}</div>
    </PanelSectionRow>
  </PanelSection>;
}

export default definePlugin(() => ({
  name: "Legion Go S Fan",
  titleView: <div className={staticClasses.Title}>Legion Go S 风扇</div>,
  content: <Content />,
  icon: <FaFan />,
}));
