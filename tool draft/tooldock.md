# Tool Dock 구현 및 EXE 배포 정리

## 1. 목적

`tools` 폴더에 Python 도구가 많아졌을 때 각 파일을 직접 찾아 실행하지 않고, 하나의 작은 창에서 등록·관리·실행하기 위한 보조 실행기입니다.

설계 원본:

```text
tool draft/tooldock.excalidraw
```

## 2. 파일 구조

```text
tools/
├── tooldock.py          # Tool Dock 본체
├── tool_registry.json   # 등록된 도구 정보
├── icons/               # 선택한 도구 아이콘 복사본
├── copytool.py          # 기존 Markdown 수집 도구
└── ToolDock.exe         # PyInstaller로 생성하는 실행 파일
```

## 3. 화면 구성

- 작은 창 크기: 최초 `380 x 420`
- 최소 창 크기: `340 x 320`
- 등록 도구를 작은 네모 아이콘 타일로 표시
- 한 줄에 최대 4개의 도구 타일 배치
- 아이콘이 없으면 기본 아이콘 표시
- 상단 버튼 구성:
  - `+`: 새 도구 등록
  - `−`: 선택 도구 등록 삭제
  - `►`: 선택 도구 실행
  - `⚙`: 선택 도구 설정

## 4. 실행 동작

- 타일 한 번 클릭: 도구 선택
- 타일 더블클릭: 도구 실행
- `►` 버튼: 현재 선택된 도구 실행
- 도구는 별도 프로세스로 실행되어 Tool Dock이 멈추지 않음
- Windows에서는 콘솔 창이 표시되지 않도록 실행

등록된 `.py` 도구는 Python 인터프리터로 실행하며, `.exe` 도구도 직접 실행할 수 있습니다.

## 5. 도구 등록

`+` 버튼을 클릭한 뒤 Python 또는 실행 파일을 선택합니다.

등록 창에서 다음 항목을 한 번에 입력합니다.

- 도구 이름
- 도구 설명
- 아이콘 이미지

지원 아이콘 형식:

```text
PNG, JPG, JPEG, ICO
```

선택한 아이콘은 프로젝트 내부로 복사됩니다.

```text
tools/icons/
```

등록 정보는 다음 JSON 파일에 저장됩니다.

```text
tools/tool_registry.json
```

## 6. 도구 설정 변경

도구를 먼저 선택한 뒤 `⚙` 버튼을 클릭하면 다음 정보를 변경할 수 있습니다.

- 이름
- 설명
- 아이콘

`기본값` 버튼을 사용하면 아이콘을 제거하고 기본 아이콘으로 되돌릴 수 있습니다.

## 7. EXE 생성

PyInstaller를 설치합니다.

```powershell
python -m pip install pyinstaller
```

프로젝트 루트에서 다음 명령을 실행합니다.

```powershell
python -m PyInstaller --noconfirm --onefile --windowed --name ToolDock --distpath tools --workpath tools/build --specpath tools/build tools/tooldock.py
```

생성 파일:

```text
tools/ToolDock.exe
```

`--windowed` 옵션으로 콘솔 창 없이 실행됩니다.

## 8. EXE 실행 시 주의 사항

Tool Dock EXE는 등록 정보와 아이콘을 EXE가 있는 폴더 기준으로 읽습니다. 따라서 다음 파일과 폴더를 `ToolDock.exe`와 함께 유지해야 합니다.

```text
tools/ToolDock.exe
tools/tool_registry.json
tools/icons/
tools/copytool.py
```

등록된 `.py` 도구를 실행하려면 대상 PC에 Python이 설치되어 있어야 하며, 해당 도구의 의존성도 설치되어 있어야 합니다.

Python이 없는 PC에서 사용하려면 각 도구도 별도의 `.exe`로 빌드한 뒤 Tool Dock에 `.exe` 파일로 등록하는 방식을 사용합니다.

## 9. 소스 실행

```powershell
python tools/tooldock.py
```
