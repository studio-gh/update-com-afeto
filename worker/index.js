/**
 * Update com Afeto · Manual refresh gateway
 *
 * Deploy as a Cloudflare Worker and configure:
 *   GITHUB_TOKEN  = fine-grained token with Actions: write on studio-gh/update-com-afeto
 *   ALLOWED_ORIGIN = https://studio-gh.github.io
 *
 * Front-end calls POST /refresh. GitHub credentials never reach the browser.
 */
const REPO = "studio-gh/update-com-afeto";
const WORKFLOW = "daily-edition.yml";

function cors(origin, allowed) {
  return {
    "Access-Control-Allow-Origin": origin === allowed ? allowed : "null",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Vary": "Origin"
  };
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const headers = cors(origin, env.ALLOWED_ORIGIN);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers });
    }
    if (origin !== env.ALLOWED_ORIGIN) {
      return Response.json({ ok: false, message: "Origem não autorizada." }, { status: 403, headers });
    }
    const url = new URL(request.url);
    if (url.pathname !== "/refresh" || request.method !== "POST") {
      return Response.json({ ok: false, message: "Rota não encontrada." }, { status: 404, headers });
    }
    if (!env.GITHUB_TOKEN) {
      return Response.json({ ok: false, message: "Integração não configurada." }, { status: 503, headers });
    }

    const response = await fetch(
      `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
      {
        method: "POST",
        headers: {
          "Accept": "application/vnd.github+json",
          "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "Update-com-Afeto-Refresh"
        },
        body: JSON.stringify({ ref: "main" })
      }
    );

    if (response.status !== 204) {
      return Response.json({
        ok: false,
        message: "Não foi possível iniciar a atualização. Tente novamente em instantes."
      }, { status: 502, headers });
    }
    return Response.json({
      ok: true,
      message: "Apuração iniciada. A edição será publicada depois da validação."
    }, { status: 202, headers });
  }
};
