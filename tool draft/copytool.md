# CopyTool 구현 정리

## 1. 목적

웹 브라우저 등에서 복사한 참고자료를 CustomTkinter 기반 Python 프로그램에 붙여넣고, 텍스트·이미지·표가 포함된 Markdown 문서로 정리하는 도구입니다.

설계 원본:

```text
tool draft/copytool.excalidraw
```

## 2. 파일 위치

```text
tools/
├── copytool.py          # 애플리케이션 본체
├── requirements.txt     # Python 패키지 목록
├── README.md            # 사용 설명서
└── result/
    ├── .gitkeep
    └── images/          # 로컬 이미지 저장 위치
        └── .gitkeep
```

기본 Markdown 저장 위치:

```text
C:\MyDoc\workspace\AssetCommon\tools\result
```

## 3. 주요 기능

### 클립보드 붙여넣기

- `Ctrl+V` 또는 `클립보드 붙여넣기` 버튼 지원
- Windows HTML Clipboard Format 우선 처리
- 일반 텍스트 클립보드 fallback 지원
- 이미지 전용 클립보드 지원

### Markdown 변환

- 제목: `h1`~`h6` → Markdown 제목
- 굵게, 기울임, 취소선, 인라인 코드
- 목록 및 순서 목록
- 링크
- HTML 표 → Markdown 표
- HTML 이미지 → Markdown 이미지 링크
- Base64 이미지 저장

### 편집 및 미리보기

화면은 다음과 같이 구성됩니다.

```text
┌────────────────────────────────────────────────────┐
│ 클립보드 붙여넣기 │ 외부 이미지 로컬 변환             │
├──────────────────────┬─┬───────────────────────────┤
│ Markdown 편집         │↔│ md 미리보기                │
│                      │ │                           │
├──────────────────────┴─┴───────────────────────────┤
│ 저장 폴더 / 파일명 / md로 저장                       │
└────────────────────────────────────────────────────┘
```

- 왼쪽에서 Markdown을 직접 수정할 수 있습니다.
- 오른쪽 미리보기는 제목, 강조, 코드, 표, 목록, 이미지를 반영합니다.
- 편집 내용을 변경하면 미리보기가 자동 갱신됩니다.
- 편집 영역과 미리보기 영역 사이의 슬라이더를 드래그하여 너비를 조절할 수 있습니다.

## 4. 이미지 처리

### 이미지 로컬 저장

클립보드 이미지와 HTML의 Base64 이미지는 항상 다음 위치에 저장하고 Markdown에는 상대 경로를 기록합니다.

```text
<Markdown 저장 폴더>/images/
```

기본 저장 폴더를 사용할 경우:

```text
tools/result/images/
```

Markdown 예시:

```markdown
![clipboard image](images/clipboard_001.png)
```

외부 이미지 URL은 붙여넣을 때 원본 URL을 유지하며, 필요한 경우 `외부 이미지 로컬 변환` 버튼으로 다운로드합니다.

### 외부 이미지 로컬 변환

`외부 이미지 로컬 변환` 버튼은 현재 편집 중인 Markdown의 다음 형식을 검색합니다.

```markdown
![설명](https://example.com/image.png)
```

버튼을 누르면:

1. 외부 이미지를 다운로드합니다.
2. 실제 이미지인지 검증합니다.
3. `images/` 폴더에 PNG로 저장합니다.
4. Markdown 링크를 로컬 상대 경로로 변경합니다.
5. 오른쪽 미리보기를 갱신합니다.

외부 이미지 파일명은 URL SHA-256 해시 일부를 사용하여 같은 URL의 중복 저장을 방지합니다.

```markdown
![설명](images/external_a1b2c3d4e5f6.png)
```

이미지 다운로드에는 다음 제한이 적용됩니다.

- HTTP/HTTPS만 허용
- 이미지당 최대 25MB
- 실제 이미지 형식 검증
- 요청 timeout 15초

## 5. Markdown 저장

1. 클립보드 내용을 붙여넣습니다.
2. 필요한 경우 Markdown을 직접 수정합니다.
3. 저장 폴더를 선택합니다.
4. 파일명을 입력합니다.
5. `md로 저장`을 누릅니다.

저장 후 파일명 입력란은 다음 문서를 위한 새 이름으로 자동 변경됩니다.

```text
reference_YYYYMMDD_HHMMSS_microseconds.md
```

## 6. 설치 및 실행

프로젝트 루트에서 실행합니다.

```powershell
python -m pip install -r tools/requirements.txt
python tools/copytool.py
```

주요 의존성:

```text
customtkinter
Pillow
pywin32       # Windows 클립보드 HTML/텍스트 처리
```

## 7. Git 관리

로컬 이미지가 저장소를 불필요하게 크게 만들지 않도록 다음 경로는 Git에서 제외됩니다.

```text
tools/result/images/*
```

`images/.gitkeep`만 Git으로 추적하여 폴더 구조를 유지합니다.
