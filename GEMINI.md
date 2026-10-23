# HousePrice 프로젝트 규칙

- **작업 경로**: `C:\Users\SeungIn\.gemini\antigravity\scratch\HousePrice` (`https://github.com/seunginp/HousePrice`)
- **파일 동기화**: GitHub Pages 배포용 루트 파일(`index.html`, `data.js`)과 `frontend/` 폴더 내부 파일(`frontend/index.html`, `frontend/data.js`)은 수정 시 항상 동일하게 동기화(복사)한다.
- **자동 배포**: 기능 추가·수정 작업이 완료되면 즉시 `git add`, `git commit`, `git push origin main`, 그리고 GitHub Pages 배포 브랜치 동기화를 위해 `git push origin main:gh-pages --force`까지 자동으로 실행하여 GitHub Pages(`https://seunginp.github.io/HousePrice/`)에 즉시 반영한다.
