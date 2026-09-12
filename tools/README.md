# CopyTool

웹 페이지에서 복사한 내용을 붙여넣어 Markdown으로 정리하는 CustomTkinter 도구입니다.

## 설치 및 실행

```powershell
python -m pip install -r tools/requirements.txt
python tools/copytool.py
```

## 지원 내용

- `HTML Format` 기반 텍스트와 제목, 목록, 링크
- HTML 표를 Markdown 표로 변환
- HTML의 Base64 이미지 저장 및 Markdown 링크 생성
- 이미지 전용 클립보드 내용 PNG 저장
- HTML을 제공하지 않는 프로그램의 일반 텍스트 fallback
- 저장 폴더 선택 및 Markdown 파일명 지정
- 클립보드 이미지와 Base64 이미지를 `<저장폴더>/images/`에 저장하고 Markdown에서 상대 경로로 읽기
- `외부 이미지 로컬 변환` 버튼: 현재 Markdown의 `http://`/`https://` 이미지 주소를 다운로드해 `images/`에 PNG로 저장하고 링크를 자동 교체합니다.
- Markdown 편집 내용의 실시간 미리보기(제목, 강조, 코드, 표, 이미지)
- Markdown 편집 영역과 미리보기 영역 사이의 가변 슬라이더
- 저장 완료 후 다음 문서용 파일명을 자동 생성

기본 저장 위치는 `tools/result/`이며, 로컬 이미지는 `tools/result/images/`에 저장됩니다.
