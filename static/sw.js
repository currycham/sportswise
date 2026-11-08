// Only cache the offline page shell. Personal API responses are never cached.
const CACHE='sportswise-shell-v13';
self.addEventListener('install',event=>{event.waitUntil(caches.open(CACHE).then(c=>c.addAll(['/static/style.css?v=13','/static/movement-guides.js?v=13','/static/app.js?v=13','/static/icon.svg'])));self.skipWaiting()});
self.addEventListener('activate',event=>{event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));self.clients.claim()});
self.addEventListener('fetch',event=>{const u=new URL(event.request.url);if(u.origin!==location.origin||!u.pathname.startsWith('/static/'))return;event.respondWith(fetch(event.request).catch(()=>caches.match(event.request)))});
