function midTrunc(name, max = 40) {
  if (name.length <= max) return name;
  const dot  = name.lastIndexOf(".");
  const ext  = dot > 0 ? name.slice(dot) : "";
  const base = dot > 0 ? name.slice(0, dot) : name;
  const keep = max - ext.length - 3;
  const head = Math.ceil(keep / 2);
  const tail = Math.floor(keep / 2);
  return base.slice(0, head) + "…" + base.slice(-tail) + ext;
}

function extractDriveId(url) {
  const m = url.match(/\/file\/d\/([a-zA-Z0-9_-]+)/);
  return m ? m[1] : url;
}

function isValidDriveUrl(val) {
  if (!val) return false;
  if (/drive\.google\.com\/(u\/\d+\/)?file\/d\/[a-zA-Z0-9_-]+/.test(val)) return true;
  if (/^[a-zA-Z0-9_-]{25,60}$/.test(val)) return true;
  return false;
}

function isValidZoomUrl(val) {
  return /https?:\/\/[^/]*\.?zoom\.us\/rec\//.test(val);
}

function esc(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function fmtB(b) {
  if (b >= 1e9) return (b / 1e9).toFixed(2) + " GB";
  if (b >= 1e6) return (b / 1e6).toFixed(1) + " MB";
  if (b >= 1e3) return (b / 1e3).toFixed(0) + " KB";
  return b + " B";
}

function fmtSpd(bps) {
  if (bps >= 1e6) return (bps / 1e6).toFixed(1) + " MB/s";
  if (bps >= 1e3) return (bps / 1e3).toFixed(0) + " KB/s";
  return bps + " B/s";
}

function fmtEta(s) {
  if (!isFinite(s) || s <= 0) return "";
  if (s < 60)   return Math.ceil(s) + "s left";
  if (s < 3600) return Math.ceil(s / 60) + "m left";
  return (s / 3600).toFixed(1) + "h left";
}

function fmtDate(iso) {
  const d = new Date(iso);
  return (
    d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) +
    " · " +
    d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
  );
}
