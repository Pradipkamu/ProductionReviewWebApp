ssh -i "$HOME\\.ssh\\ssh-key-2026-10-05.key" ubuntu@92.4.90.35

**Next block**
cd /home/ubuntu/ProductionReviewWebApp || exit 1

echo "======================================"
echo "1. CURRENT PRODUCTION STATE"
echo "======================================"
git status --short
OLD\_COMMIT=$(git rev-parse HEAD)
echo "Current commit: $OLD\_COMMIT"

echo
echo "======================================"
echo "2. CREATE ROLLBACK TAG"
echo "======================================"
ROLLBACK\_TAG="pre\_searchable\_ui\_$(date +%Y%m%d\_%H%M%S)"
git tag "$ROLLBACK\_TAG" "$OLD\_COMMIT"
echo "Rollback tag: $ROLLBACK\_TAG"

echo
echo "======================================"
echo "3. FETCH GITHUB MAIN"
echo "======================================"
git fetch origin main

echo "Server : $(git rev-parse --short HEAD)"
echo "GitHub : $(git rev-parse --short origin/main)"

echo
echo "======================================"
echo "4. VERIFY REQUIRED COMMIT"
echo "======================================"
git merge-base --is-ancestor e05f38b origin/main   
\&\& echo "OK - e05f38b is included in origin/main"   
|| { echo "STOP - e05f38b is not in origin/main"; exit 1; }

echo
echo "======================================"
echo "5. UPDATE SERVER SOURCE"
echo "======================================"
git checkout --detach origin/main
NEW\_COMMIT=$(git rev-parse HEAD)
echo "Now running source: $NEW\_COMMIT"

echo
echo "======================================"
echo "6. RECORD OLD FRONTEND IMAGE"
echo "======================================"
OLD\_IMAGE=$(sudo docker inspect productionreviewwebapp-frontend-1   
--format '{{.Image}}' 2>/dev/null || true)
echo "Old frontend image: $OLD\_IMAGE"

echo
echo "======================================"
echo "7. BUILD FRESH FRONTEND"
echo "======================================"
sudo docker compose build --no-cache frontend || exit 1

echo
echo "======================================"
echo "8. FORCE RECREATE FRONTEND"
echo "======================================"
sudo docker compose up -d --force-recreate --no-deps frontend || exit 1

echo
echo "======================================"
echo "9. VERIFY NEW CONTAINER"
echo "======================================"
sudo docker compose ps frontend

NEW\_IMAGE=$(sudo docker inspect productionreviewwebapp-frontend-1   
--format '{{.Image}}')
echo "Old image: $OLD\_IMAGE"
echo "New image: $NEW\_IMAGE"

if \[ "$OLD\_IMAGE" = "$NEW\_IMAGE" ]; then
echo "WARNING: frontend image ID did not change"
else
echo "OK - frontend container is using a new image"
fi

echo
echo "======================================"
echo "10. PUBLIC HTTPS CHECK"
echo "======================================"
curl -k -I https://machineshop.duckdns.org/ || exit 1

echo
echo "======================================"
echo "DEPLOYMENT RESULT"
echo "======================================"
echo "Git commit : $(git rev-parse --short HEAD)"
echo "Rollback   : $ROLLBACK\_TAG"
echo "Frontend   : $NEW\_IMAGE"





**BACK UP FROM ORACLE and install in windows**
cd "D:\\Machine Shop MIS"

powershell -NoProfile -ExecutionPolicy Bypass `
-File ".\\Backup\_Oracle\_Review\_To\_Windows.ps1"





\*\*\* ALL TABLE Name \*\*\*

docker compose exec -T db psql -U pms -d pms -c "\\dt"



\*\* User Id Change \*\*\*\*

cd /home/ubuntu/ProductionReviewWebApp

docker compose exec -T db psql -U pms -d pms -c   
"SELECT id, username, full\_name, role, is\_active FROM users WHERE lower(username) LIKE '%wassim%' OR lower(full\_name) LIKE '%wassim%';"



docker compose exec -T db psql -v ON\_ERROR\_STOP=1 -U pms -d pms <<'SQL'
BEGIN;

UPDATE users
SET username = 'vasim',
full\_name = 'Vasim Sayyad'
WHERE id = 11
AND username = 'wassim';

COMMIT;

SELECT id, username, full\_name, role, is\_active
FROM users
WHERE id = 11;
SQL

