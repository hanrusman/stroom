# TODO voor PR Review

## NPM Setup (via Web UI)

Deze applicatie vereist npm packages die geïnstalleerd moeten worden via de web UI:

### Vereiste packages:
- `react` en `react-dom` (reeds in package.json)
- `motion/react` voor animaties
- `marked` en `dompurify` voor markdown rendering
- `lucide-react` voor iconen
- Tailwind CSS via Vite plugin

### Installatie stappen:
1. Log in op de web UI van de VPS
2. Navigeer naar `/opt/stacks/vps-stacks/stroom-src/web/`
3. Run: `npm install`
4. Controleer of `node_modules` correct wordt aangemaakt
5. Test build: `npm run build`

### Troubleshooting:
- Als npm niet beschikbaar is in web UI, controleer of Node.js is geïnstalleerd
- Alternatief: SSH naar de VPS en run npm install handmatig

## Logo Update

Nieuw logo beschikbaar op:
`/Users/hanrusman/Downloads/stitch (3)/screen.png`

Acties:
- [ ] Logo converteren naar favicon formaten (16x16, 32x32, 180x180)
- [ ] Update `web/index.html` favicon link
- [ ] Update header logo in `web/src/App.tsx`
- [ ] Test op verschillende devices (iOS, Android, desktop)

## Post-Deploy Checks

- [ ] Rate limiting werkt (test met meerdere snelle requests)
- [ ] Security headers aanwezig (check via securityheaders.com)
- [ ] SQL injection gefixt (test search met speciale karakters)
- [ ] Stats panel laadt correct in admin
- [ ] Mobile responsive werkt (test op telefoon)

## Rollback Plan

Mocht er iets misgaan:
```bash
# Revert commits
git revert dcc4b6a  # API changes
git revert 3b80770  # Nginx changes

# Restart services
docker restart stroom-api stroom-web
```
