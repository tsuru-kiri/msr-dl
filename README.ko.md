# msr-dl

[English](README.md)
[Korean](README.ko.md)

Monster Siren Records 음원을 앨범 아트, 메타데이터, 싱크 가사와 함께
내려받는 명령줄 도구입니다.

## 주요 기능

- 전체 카탈로그 또는 앨범·곡 CID 단위 다운로드
- 중단 후 재실행할 수 있는 다운로드 상태 관리
- 앨범 아트와 LRC 가사를 파일에 삽입
- PRTS Wiki를 보완 데이터로 사용해 발매일과 누락된 아티스트 정보 추가

## 빠른 시작

Python 3.10–3.13과 `PATH`에서 실행 가능한 FFmpeg가 필요합니다.

```bash
python -m pip install -e .
msr-dl list
msr-dl download --album-cid 0239
```

인자 없이 실행하면 전체 카탈로그를 `./MonsterSiren`에 내려받습니다.

```bash
msr-dl
```

출력 위치나 동시 작업 수를 바꿀 수도 있습니다.

```bash
msr-dl download --output ~/Music/MonsterSiren --workers 2
```

## 문서

- [사용법](docs/usage.md): 대상 선택, 옵션, 출력 구조, 실행 시 주의사항
- [PRTS 메타데이터](docs/metadata.md): 스냅샷 갱신 및 기존 파일에 적용
- [개발 가이드](docs/development.md): 개발 환경, 테스트, 빌드, 내부 구조
