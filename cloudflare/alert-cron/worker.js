// Balance Lab 깨우기 (2026-11-25 사용자 확정)
// 깃허브의 '정해진 시각 실행'이 1~2시간씩 늦거나 건너뛰어서(웹 배포 21:10 회차가 새벽에 돈 날도 있음),
// Cloudflare가 10분마다 시각을 보고 제시각에 깃허브 작업을 "지금 돌려라"는 신호만 보낸다. 일은 그대로 깃허브에서 돈다.
//   · 장중 알림(alerts.yml): 평일 09:00~15:40, 20분마다
//   · 웹 배포(web-deploy.yml): 평일 07:20·10:20·12:20·15:20·16:40·18:20·21:10 · 토 10:30·12:40·20:40 · 일 12:40·20:40 (web-deploy.yml의 시각표와 같게 유지)
// 주문 기능 없음 · Claude 토큰 0 · 열쇠(GH_TOKEN)는 Cloudflare 비밀 값으로만 읽는다(코드·저장소에 쓰지 않음).
const REPO = "livegym7/stock_team";
const DEPLOY = { wd: ["07:20", "10:20", "12:20", "15:20", "16:40", "18:20", "21:10"], sat: ["10:30", "12:40", "20:40"], sun: ["12:40", "20:40"] };

// 예약 시각(UTC ms) → 그 시각에 깨울 작업 목록. 10분 단위로 내림해서 본다(예약이 몇 초 늦게 불려도 같은 칸)
function due(ms) {
  const k = new Date(ms + 9 * 3600 * 1000), dow = k.getUTCDay(), m = Math.floor(k.getUTCMinutes() / 10) * 10, mins = k.getUTCHours() * 60 + m;
  const hm = `${String(k.getUTCHours()).padStart(2, "0")}:${String(m).padStart(2, "0")}`, out = [];
  const weekday = dow >= 1 && dow <= 5;
  if (weekday && mins >= 540 && mins <= 940 && m % 20 === 0) out.push("alerts.yml");
  if ((weekday ? DEPLOY.wd : dow === 6 ? DEPLOY.sat : DEPLOY.sun).includes(hm)) out.push("web-deploy.yml");
  return out;
}

async function wake(env, workflow) {
  if (!env.GH_TOKEN) return { workflow, ok: false, why: "GH_TOKEN 비밀 값이 없습니다" };
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${workflow}/dispatches`, {
    method: "POST",
    headers: { "Authorization": `Bearer ${env.GH_TOKEN}`, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "balance-lab-alert-cron", "Content-Type": "application/json" },
    body: JSON.stringify({ ref: "main" }),
  });
  return { workflow, ok: r.status === 204, status: r.status };
}

export default {
  async scheduled(event, env, ctx) {
    for (const w of due(event.scheduledTime)) console.log("wake", JSON.stringify(await wake(env, w)));
  },
  // 주소를 열어도 아무 일도 하지 않는다(상태 글자만). 깨우기는 예약으로만 돈다.
  async fetch() {
    return new Response("balance-lab cron: 제시각에 깃허브의 장중 알림·웹 배포 작업을 깨웁니다", { headers: { "content-type": "text/plain; charset=utf-8" } });
  },
};
