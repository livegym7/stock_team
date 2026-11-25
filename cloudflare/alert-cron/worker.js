// Balance Lab 알림 깨우기 (2026-11-25 사용자 확정)
// 깃허브의 '정해진 시각 실행'이 1~2시간씩 늦거나 건너뛰어서, Cloudflare가 평일 장중 20분마다
// 깃허브에 "장중 알림 작업(alerts.yml)을 지금 돌려라"는 신호만 보낸다. 확인·알림은 그대로 깃허브에서 돈다.
// 주문 기능 없음 · Claude 토큰 0 · 열쇠(GH_TOKEN)는 Cloudflare 비밀 값으로만 읽는다(코드·저장소에 쓰지 않음).
const REPO = "livegym7/stock_team", WORKFLOW = "alerts.yml";

async function wake(env) {
  if (!env.GH_TOKEN) return { ok: false, why: "GH_TOKEN 비밀 값이 없습니다" };
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    headers: { "Authorization": `Bearer ${env.GH_TOKEN}`, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "balance-lab-alert-cron", "Content-Type": "application/json" },
    body: JSON.stringify({ ref: "main" }),
  });
  return { ok: r.status === 204, status: r.status };
}

export default {
  async scheduled(event, env, ctx) {
    const res = await wake(env);
    console.log("wake", JSON.stringify(res));
  },
  // 주소를 열어도 아무 일도 하지 않는다(상태 글자만). 깨우기는 예약으로만 돈다.
  async fetch() {
    return new Response("balance-lab alert cron: 평일 장중 20분마다 깃허브 알림 작업을 깨웁니다", { headers: { "content-type": "text/plain; charset=utf-8" } });
  },
};
