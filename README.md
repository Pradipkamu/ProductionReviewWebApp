ssh -i "$HOME\.ssh\ssh-key-2026-10-05.key" ubuntu@92.4.90.35

**Next block**
cd /home/ubuntu/ProductionReviewWebApp || exit 1

echo "======================================"
echo "1. CURRENT PRODUCTION STATE"
echo "======================================"
git status --short
OLD_COMMIT=$(git rev-parse HEAD)
echo "Current commit: $OLD_COMMIT"

echo
echo "======================================"
echo "2. CREATE ROLLBACK TAG"
echo "======================================"
ROLLBACK_TAG="pre_searchable_ui_$(date +%Y%m%d_%H%M%S)"
git tag "$ROLLBACK_TAG" "$OLD_COMMIT"
echo "Rollback tag: $ROLLBACK_TAG"

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
git merge-base --is-ancestor e05f38b origin/main \
  && echo "OK - e05f38b is included in origin/main" \
  || { echo "STOP - e05f38b is not in origin/main"; exit 1; }

echo
echo "======================================"
echo "5. UPDATE SERVER SOURCE"
echo "======================================"
git checkout --detach origin/main
NEW_COMMIT=$(git rev-parse HEAD)
echo "Now running source: $NEW_COMMIT"

echo
echo "======================================"
echo "6. RECORD OLD FRONTEND IMAGE"
echo "======================================"
OLD_IMAGE=$(sudo docker inspect productionreviewwebapp-frontend-1 \
  --format '{{.Image}}' 2>/dev/null || true)
echo "Old frontend image: $OLD_IMAGE"

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

NEW_IMAGE=$(sudo docker inspect productionreviewwebapp-frontend-1 \
  --format '{{.Image}}')
echo "Old image: $OLD_IMAGE"
echo "New image: $NEW_IMAGE"

if [ "$OLD_IMAGE" = "$NEW_IMAGE" ]; then
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
echo "Rollback   : $ROLLBACK_TAG"
echo "Frontend   : $NEW_IMAGE"