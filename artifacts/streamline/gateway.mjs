/**
 * Transparent same-origin gateway to the existing Python checkout.
 * No business logic, state, secrets, or workers belong in this process.
 * The upstream is server-only; browsers continue using the original URLs.
 */
import http from 'node:http';
import process from 'node:process';

const port = Number(process.env.PORT);
const upstreamPort = Number(process.env.STREAMBOT_UPSTREAM_PORT);
if (!Number.isInteger(port) || port < 1 || port > 65535 ||
    !Number.isInteger(upstreamPort) || upstreamPort < 1 || upstreamPort > 65535) {
  throw new Error('The web artifact must provide valid PORT and STREAMBOT_UPSTREAM_PORT.');
}

// Remove connection-specific headers, including any nominated by Connection.
function forwardedHeaders(headers) {
  const result = { ...headers };
  const hopHeaders = [
    'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
    'te', 'trailer', 'transfer-encoding', 'upgrade',
    ...String(headers.connection || '').toLowerCase().split(',').map(value => value.trim()),
  ];
  for (const name of hopHeaders) delete result[name];
  return result;
}

const server = http.createServer((request, response) => {
  const url = new URL(request.url, 'http://gateway.invalid');
  if (url.pathname === '/admin' && ['GET', 'HEAD'].includes(request.method)) {
    response.writeHead(308, { Location: '/admin/' + url.search, 'Cache-Control': 'no-store' });
    response.end();
    return;
  }
  const upstream = http.request({
    hostname: '127.0.0.1',
    port: upstreamPort,
    method: request.method,
    path: request.url,
    // Preserve Host, Origin, order tokens, and the platform forwarding chain.
    // Flask remains responsible for origin checks, rate limits, and CSP.
    headers: forwardedHeaders(request.headers),
    timeout: 30_000,
  }, incoming => {
    response.writeHead(incoming.statusCode, forwardedHeaders(incoming.headers));
    incoming.pipe(response);
    incoming.on('error', () => response.destroy());
  });
  upstream.on('timeout', () => upstream.destroy());
  upstream.on('error', () => {
    if (response.headersSent) return response.destroy();
    response.writeHead(503, {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-store',
      'Retry-After': '3',
      'X-Content-Type-Options': 'nosniff',
      'X-Frame-Options': 'DENY',
      'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'",
    });
    response.end(JSON.stringify({error: 'The checkout is starting. Please retry shortly.'}));
  });
  request.on('aborted', () => upstream.destroy());
  response.on('close', () => { if (!response.writableFinished) upstream.destroy(); });
  request.pipe(upstream);
});
server.listen(port, '0.0.0.0');
for (const signal of ['SIGTERM', 'SIGINT']) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
