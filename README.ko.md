# msr-dl

[English](README.md)

Monster Siren Records 음원을 앨범 아트, 메타데이터, 싱크 가사와 함께
내려받는 명령줄 도구입니다.

## 주요 기능

- 전체 카탈로그 또는 앨범·곡 CID 단위 다운로드
- 중단 후 재실행할 수 있는 다운로드 상태 관리
- 앨범 아트와 LRC 가사를 파일에 삽입
- PRTS Wiki를 보완 데이터로 사용해 발매일과 누락된 아티스트 정보 추가

## 빠른 시작

### 설치

macOS 또는 Linux에서는 다음 설치 명령을 실행합니다. 새 릴리스가 있을 때
같은 명령을 다시 실행하면 업데이트됩니다.

```sh
curl -LsSf https://github.com/tsuru-kiri/msr-dl/releases/latest/download/install.sh | sh
```

Intel·Apple Silicon macOS와 x86_64·ARM64 64비트 glibc Linux를 지원합니다.
관리자 권한 없이 `uv`, msr-dl과 필요한 경우 전용 FFmpeg를 설치합니다.

Windows에서는 PowerShell을 열고 다음 설치 명령을 실행합니다. 새 릴리스가
있을 때 같은 명령을 다시 실행하면 업데이트됩니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -c "irm https://github.com/tsuru-kiri/msr-dl/releases/latest/download/install.ps1 | iex"
```

관리자 권한 없이 `uv`, msr-dl과 전용 FFmpeg를 설치합니다.

macOS에서는 Homebrew formula를 대안으로 사용할 수 있습니다.

```bash
brew install tsuru-kiri/tap/msr-dl
```

소스에서 직접 실행하려면 Python 3.11–3.13과 `PATH`에서 실행 가능한
FFmpeg가 필요합니다.

```bash
python -m pip install -e .
```

### 실행

인자 없이 실행하면 전체 카탈로그를 `./MonsterSiren`에 내려받습니다.

```bash
msr-dl
```

카탈로그를 조회하거나 특정 앨범을 내려받을 수 있으며, 출력 위치와 동시
작업 수도 지정할 수 있습니다.

```bash
msr-dl list
msr-dl download --album-cid 0239
msr-dl download --output ~/Music/MonsterSiren --workers 2
```

## 면책 안내

msr-dl은 비공식 프로젝트이며 Hypergryph 또는 Monster Siren Records와
관련이 없고, 이들로부터 승인이나 보증을 받지 않았습니다. 음원, 앨범 아트,
가사, 상표 및 관련 자료의 권리는 각 권리자에게 있습니다.

이 프로젝트에는 다운로드된 미디어가 포함되어 있지 않습니다. 사용자는 본
도구의 이용이 관련 법률과 원본 서비스의 이용 조건을 준수하는지 직접 확인할
책임이 있습니다. 또한 다운로드한 콘텐츠의 재배포 또는 상업적 이용과 그로
인해 발생하는 모든 결과에 대한 책임도 전적으로 사용자에게 있습니다.

## 감사의 말

이 프로젝트는
[khanhn201/monster-siren-download](https://github.com/khanhn201/monster-siren-download)에서
영감을 받았습니다.

## 라이선스

msr-dl은 [MIT 라이선스](LICENSE)로 배포됩니다. 포함된 외부 저작물에 관한
내용은 [제3자 고지](THIRD_PARTY_NOTICES)를 참고하십시오.

## 문서

- [사용법](docs/usage.md): 대상 선택, 옵션, 출력 구조, 실행 시 주의사항
- [PRTS 메타데이터](docs/metadata.md): 스냅샷 갱신 및 기존 파일에 적용
- [개발 가이드](docs/development.md): 개발 환경, 테스트, 빌드, 내부 구조
