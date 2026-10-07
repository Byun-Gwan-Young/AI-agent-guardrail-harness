"""Storage를 초보자도 짧은 명령/메뉴로 실행할 수 있게 하는 진입점."""

import argparse
from pathlib import Path

from storage.db import get_project_id
from storage.import_demo import demo_folders, import_all_demos, import_demo
from storage.import_run import import_run
from storage.import_utils import PROJECT_ROOT
from storage.init_db import initialize_everything, list_projects


def raw_folders():
    """실제 raw import에 필요한 파일이 모두 있는 runs 폴더만 보여준다."""
    root = PROJECT_ROOT / "runs"
    if not root.is_dir():
        return []

    required = ("summary.json", "session.json", "conditions.json", "scenario.yaml")
    return sorted(
        folder
        for folder in root.iterdir()
        if folder.is_dir() and all((folder / name).is_file() for name in required)
    )


def choose_folder(folders, title, search=False):
    if not folders:
        raise FileNotFoundError(f"선택할 {title} 폴더가 없습니다.")

    choices = list(folders)
    if search:
        keyword = input("검색어 (예: DEMO-CL-normal-v1, Enter=전체): ").strip()
        if keyword:
            choices = [folder for folder in choices if keyword.lower() in folder.name.lower()]
        if not choices:
            raise ValueError("검색어와 일치하는 demo가 없습니다.")

    # demo가 너무 많으면 먼저 검색하도록 안내한다.
    if len(choices) > 30:
        print(f"검색 결과가 {len(choices)}개입니다. 검색어를 더 구체적으로 입력하세요.")
        return choose_folder(choices, title, search=True)

    print(f"\n[{title} 선택]")
    for index, folder in enumerate(choices, start=1):
        print(f"{index}. {folder.name}")

    while True:
        raw = input("번호: ").strip()
        try:
            number = int(raw)
        except ValueError:
            print("숫자를 입력하세요.")
            continue
        if 1 <= number <= len(choices):
            return choices[number - 1]
        print("목록 안의 번호를 입력하세요.")


def show_projects():
    rows = list_projects()
    if not rows:
        print("등록된 프로젝트가 없습니다.")
        return
    print("\n[projects]")
    for row in rows:
        print(f"id={row[0]} | {row[1]} | mode={row[2]} | rule={row[3]} | {row[4]}")


def interactive_menu():
    """`python -m storage`만 입력하면 사용할 수 있는 간단 메뉴."""
    while True:
        print(
            "\n=== Guardrail Storage ===\n"
            "1. DB/스키마 초기화 (pgAdmin 없이)\n"
            "2. raw run 저장\n"
            "3. demo 1개 저장\n"
            "4. demo 전체 저장\n"
            "5. 프로젝트 목록\n"
            "0. 종료"
        )
        choice = input("선택: ").strip()

        try:
            if choice == "1":
                initialize_everything(interactive_project=True)
            elif choice == "2":
                folder = choose_folder(raw_folders(), "raw run")
                import_run(str(folder), get_project_id())
            elif choice == "3":
                folder = choose_folder(demo_folders(), "demo", search=True)
                session_id, count = import_demo(str(folder), get_project_id())
                print("demo PostgreSQL 저장 성공")
                print("session_id:", session_id)
                print("judgements:", count)
                print("observations: 0 (demo record 원본 없음)")
                print("llm_calls: 0 (demo record 원본 없음)")
            elif choice == "4":
                confirm = input("runs/demo 전체를 저장할까요? (y/N): ").strip().lower()
                if confirm == "y":
                    import_all_demos(get_project_id())
            elif choice == "5":
                show_projects()
            elif choice == "0":
                return
            else:
                print("0~5 중에서 선택하세요.")
        except Exception as exc:
            print(f"오류: {exc}")


def command_line():
    parser = argparse.ArgumentParser(
        description="Guardrail Storage 간단 실행기. 인자 없이 실행하면 메뉴가 열립니다."
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="DB + schema 초기화")

    run_parser = sub.add_parser("run", help="raw run 저장")
    run_parser.add_argument("run", nargs="?", help="폴더명/짧은 prefix. 생략하면 메뉴 선택")

    demo_parser = sub.add_parser("demo", help="demo 1개 저장")
    demo_parser.add_argument("run", nargs="?", help="폴더명/짧은 prefix. 생략하면 메뉴 선택")

    sub.add_parser("demo-all", help="demo 전체 저장")
    sub.add_parser("projects", help="프로젝트 목록")

    args = parser.parse_args()
    if args.command is None:
        interactive_menu()
        return

    if args.command == "init":
        initialize_everything(interactive_project=True)
        return

    if args.command == "projects":
        show_projects()
        return

    project_id = get_project_id()

    if args.command == "run":
        value = args.run
        if not value:
            value = str(choose_folder(raw_folders(), "raw run"))
        import_run(value, project_id)
    elif args.command == "demo":
        value = args.run
        if not value:
            value = str(choose_folder(demo_folders(), "demo", search=True))
        session_id, count = import_demo(value, project_id)
        print("demo PostgreSQL 저장 성공")
        print("session_id:", session_id)
        print("judgements:", count)
        print("observations: 0 (demo record 원본 없음)")
        print("llm_calls: 0 (demo record 원본 없음)")
    elif args.command == "demo-all":
        import_all_demos(project_id)


if __name__ == "__main__":
    command_line()
