/**
 * CampusPulse AI — WhatsApp live bridge (READ-ONLY)
 *
 * Links your WhatsApp number the same way WhatsApp Web does (scan a QR code
 * from your phone), then writes messages from the groups YOU select into
 * ../data/live/ where CampusPulse AI imports them.
 *
 *  - Never sends, deletes or reads anything outside the selected groups.
 *  - Session is stored locally in ./.wwebjs_auth (delete it, or run
 *    `npm run logout`, to unlink).
 *  - Unofficial: uses whatsapp-web.js, which automates WhatsApp Web. This is
 *    against WhatsApp's Terms of Service and may get the number restricted.
 *    Use a number you can afford to lose for demos.
 *
 * Run:  npm install   then   npm start
 */
const fs = require("fs");
const path = require("path");
const qrcodeTerminal = require("qrcode-terminal");
const QRCode = require("qrcode");
const { Client, LocalAuth } = require("whatsapp-web.js");

// The web app starts one bridge per user and passes their own folder + session id.
const LIVE_DIR = path.resolve(process.env.CP_LIVE_DIR || path.join(__dirname, "..", "data", "live"));
const SESSION_ID = (process.env.CP_SESSION_ID || "default").replace(/[^\w-]/g, "_");
const MSG_DIR = path.join(LIVE_DIR, "messages");
const MEDIA_DIR = path.join(LIVE_DIR, "media");
const STATUS_FILE = path.join(LIVE_DIR, "status.json");
const GROUPS_FILE = path.join(LIVE_DIR, "groups.json");
const SELECTED_FILE = path.join(LIVE_DIR, "selected_groups.json");
const COMMAND_FILE = path.join(LIVE_DIR, "command.json");
const BACKFILL_FILE = path.join(LIVE_DIR, "backfilled.json");
const QR_FILE = path.join(LIVE_DIR, "qr.png");
const AVATAR_FILE = path.join(LIVE_DIR, "profile.jpg");

const BACKFILL_LIMIT = parseInt(process.env.BACKFILL_LIMIT || "300", 10);
const SAVE_PDFS = (process.env.SAVE_PDFS || "1") !== "0";

for (const d of [LIVE_DIR, MSG_DIR, MEDIA_DIR]) fs.mkdirSync(d, { recursive: true });

// ------------------------------------------------------------------ helpers
const readJson = (file, fallback) => {
  try { return JSON.parse(fs.readFileSync(file, "utf8")); } catch { return fallback; }
};
const writeJson = (file, data) => {
  const tmp = file + ".tmp";
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2));
  fs.renameSync(tmp, file); // atomic, so Python never reads half a file
};
let status = { state: "starting", detail: "Launching WhatsApp Web…" };
const setStatus = (state, extra = {}) => {
  status = { ...status, ...extra, state, updated: new Date().toISOString(), pid: process.pid };
  writeJson(STATUS_FILE, status);
  console.log(`[status] ${state}${extra.detail ? " — " + extra.detail : ""}`);
};
const safeName = (s) => (s || "group").replace(/[^\w\-]+/g, "_").slice(0, 60);
const selectedIds = () => new Set(readJson(SELECTED_FILE, []));
const maskNumber = (n) => (n && n.length > 4 ? "•".repeat(n.length - 4) + n.slice(-4) : n || "");

const MEDIA_TYPES = new Set(["image", "video", "audio", "ptt", "document", "sticker"]);
const SYSTEM_TYPES = new Set(["e2e_notification", "notification_template", "gp2", "call_log", "protocol"]);

const contactCache = new Map();
async function senderName(msg) {
  if (msg.fromMe) return "You";
  const key = msg.author || msg.from;
  if (contactCache.has(key)) return contactCache.get(key);
  let name = (msg._data && msg._data.notifyName) || "";
  try {
    const c = await msg.getContact();
    name = c.name || c.pushname || name || c.number || "";
  } catch { /* contact lookup can fail for left members */ }
  name = name || (key || "").split("@")[0];
  contactCache.set(key, name);
  return name;
}

async function toRecord(msg, chat) {
  let kind = "text";
  if (msg.type === "revoked") kind = "deleted";
  else if (SYSTEM_TYPES.has(msg.type)) kind = "system";
  else if (MEDIA_TYPES.has(msg.type) || msg.hasMedia) kind = "media";

  const rec = {
    id: msg.id && msg.id._serialized,
    group_id: chat.id._serialized,
    group_name: chat.name,
    timestamp: msg.timestamp, // unix seconds
    sender: await senderName(msg),
    text: msg.body || "",
    wa_type: msg.type,
    kind,
    file: null,
  };
  if (kind === "media" && !rec.text) rec.text = `<${msg.type} omitted>`;

  // Save PDFs (circulars, guidelines) so CampusPulse can digest and cite them.
  if (SAVE_PDFS && msg.type === "document" && msg.hasMedia) {
    try {
      const media = await msg.downloadMedia();
      if (media && /pdf/i.test(media.mimetype || "")) {
        const fname = `${safeName(chat.name)}__${safeName(media.filename || rec.id)}.pdf`.replace(/\.pdf\.pdf$/, ".pdf");
        fs.writeFileSync(path.join(MEDIA_DIR, fname), Buffer.from(media.data, "base64"));
        rec.file = fname;
        rec.text = rec.text && !rec.text.startsWith("<") ? rec.text : `📄 ${media.filename || fname}`;
      }
    } catch (e) {
      console.warn("Could not download document:", e.message);
    }
  }
  return rec;
}

function append(rec) {
  const file = path.join(MSG_DIR, `${safeName(rec.group_name)}__${safeName(rec.group_id)}.jsonl`);
  fs.appendFileSync(file, JSON.stringify(rec) + "\n");
}

// ------------------------------------------------------------------- client
const client = new Client({
  authStrategy: new LocalAuth({ clientId: SESSION_ID, dataPath: path.join(__dirname, ".wwebjs_auth") }),
  puppeteer: {
    headless: true,
    executablePath: process.env.CHROME_PATH || undefined, // optional: use installed Chrome
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  },
});

client.on("qr", async (qr) => {
  console.log("\nScan this QR with WhatsApp → Settings → Linked devices → Link a device:\n");
  qrcodeTerminal.generate(qr, { small: true });
  try { await QRCode.toFile(QR_FILE, qr, { width: 360, margin: 2 }); } catch { /* terminal QR still works */ }
  setStatus("qr", { detail: "Waiting for you to scan the QR code" });
});

client.on("authenticated", () => setStatus("authenticated", { detail: "Logged in, loading chats…" }));
client.on("auth_failure", (m) => setStatus("auth_failure", { detail: String(m) }));
client.on("loading_screen", (pct) => setStatus("loading", { detail: `Loading chats ${pct}%` }));

async function publishGroups() {
  const chats = await client.getChats();
  const groups = chats
    .filter((c) => c.isGroup)
    .map((c) => ({
      id: c.id._serialized,
      name: c.name,
      participants: (c.participants || (c.groupMetadata && c.groupMetadata.participants) || []).length,
      unread: c.unreadCount || 0,
      last_activity: c.timestamp || null,
    }))
    .sort((a, b) => (b.last_activity || 0) - (a.last_activity || 0));
  writeJson(GROUPS_FILE, groups);
  return chats;
}

let backfilling = false;
async function backfillSelected() {
  if (backfilling) return;
  backfilling = true;
  try {
    const done = new Set(readJson(BACKFILL_FILE, []));
    const wanted = [...selectedIds()].filter((id) => !done.has(id));
    for (const id of wanted) {
      try {
        const chat = await client.getChatById(id);
        setStatus("ready", { detail: `Importing recent history of “${chat.name}”…` });
        const msgs = await chat.fetchMessages({ limit: BACKFILL_LIMIT });
        for (const m of msgs) append(await toRecord(m, chat));
        done.add(id);
        writeJson(BACKFILL_FILE, [...done]);
        console.log(`Backfilled ${msgs.length} messages from ${chat.name}`);
      } catch (e) {
        console.warn(`Backfill failed for ${id}:`, e.message);
      }
    }
    setStatus("ready", { detail: `Listening to ${selectedIds().size} selected group(s)` });
  } finally {
    backfilling = false;
  }
}

async function saveProfile() {
  const me = client.info || {};
  const account = { name: me.pushname || "", number: maskNumber(me.wid && me.wid.user),
                    platform: me.platform || "", about: "" };
  try {
    const contact = await client.getContactById(me.wid._serialized);
    account.about = (await contact.getAbout()) || "";
  } catch { /* privacy settings may hide it */ }
  try {
    const url = await client.getProfilePicUrl(me.wid._serialized);
    if (url && typeof fetch === "function") {
      const r = await fetch(url);
      if (r.ok) fs.writeFileSync(AVATAR_FILE, Buffer.from(await r.arrayBuffer()));
    }
  } catch { /* no profile photo */ }
  try { fs.unlinkSync(QR_FILE); } catch { /* already gone */ }
  return account;
}

client.on("ready", async () => {
  setStatus("ready", { detail: "Connected", account: await saveProfile() });
  await publishGroups();
  await backfillSelected();
});

// message_create also fires for messages you send yourself
client.on("message_create", async (msg) => {
  try {
    const chat = await msg.getChat();
    if (!chat.isGroup || !selectedIds().has(chat.id._serialized)) return;
    append(await toRecord(msg, chat));
    status.last_message = new Date().toISOString();
  } catch (e) {
    console.warn("Message handling error:", e.message);
  }
});

client.on("disconnected", (reason) => {
  setStatus("disconnected", { detail: String(reason) });
  setTimeout(() => process.exit(0), 500);
});

// ------------------------------------------------- control from the dashboard
let lastSelected = JSON.stringify([...selectedIds()].sort());
setInterval(async () => {
  // heartbeat so the dashboard knows the bridge is alive
  setStatus(status.state, {});
  const cmd = readJson(COMMAND_FILE, null);
  if (cmd && cmd.action === "stop") {
    try { fs.unlinkSync(COMMAND_FILE); } catch { /* ignore */ }
    setStatus("stopped", { detail: "Disconnected from the web app (session kept)" });
    await client.destroy().catch(() => {});
    process.exit(0);
  }
  if (status.state !== "ready") return;
  if (cmd && cmd.action) {
    try { fs.unlinkSync(COMMAND_FILE); } catch { /* ignore */ }
    if (cmd.action === "logout") {
      console.log("Logging out and unlinking this device…");
      await client.logout().catch(() => {});
      try { fs.unlinkSync(AVATAR_FILE); } catch { /* ignore */ }
      setStatus("logged_out", { detail: "Unlinked from WhatsApp", account: null });
      process.exit(0);
    }
    if (cmd.action === "refresh_groups") await publishGroups();
  }
  const sel = JSON.stringify([...selectedIds()].sort());
  if (sel !== lastSelected) {
    lastSelected = sel;
    await backfillSelected();
  }
}, 5000);

if (process.argv.includes("--logout")) {
  client.on("ready", async () => {
    await client.logout().catch(() => {});
    setStatus("logged_out", { detail: "Unlinked" });
    process.exit(0);
  });
}

process.on("SIGINT", async () => {
  setStatus("stopped", { detail: "Bridge stopped (session kept; npm start reconnects without a QR)" });
  await client.destroy().catch(() => {});
  process.exit(0);
});

setStatus("starting", { detail: "Launching WhatsApp Web…" });
client.initialize();
