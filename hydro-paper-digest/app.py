"""Windows desktop application; no third-party runtime dependencies."""
import argparse
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import webbrowser
import core


def desktop():
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title('수문·수자원 논문 브리핑')
            self.geometry('970x780')
            self.minsize(850, 680)
            try:
                self.config_data = core.load_config()
            except Exception:
                self.config_data = core.DEFAULTS.copy()
                messagebox.showwarning('설정 읽기 실패', '기존 설정을 읽지 못했습니다. 설정을 확인하고 다시 저장하세요.')
            self.busy = False
            self.events = queue.Queue()
            self.last_day, self.last_attempt = None, 0
            body = ttk.Frame(self, padding=16)
            body.pack(fill='both', expand=True)
            ttk.Label(body, text='매일 두 편, 수문·수자원 논문 브리핑', font=('Malgun Gothic', 18, 'bold')).pack(anchor='w')
            ttk.Label(body, text='홍수 · 가뭄 · 기후변화 시나리오 · AI 예측 / 한국시간 00:00 / 해외(영어) + 한국어').pack(anchor='w', pady=5)
            form = ttk.LabelFrame(body, text='연결 설정 (키는 이 PC에 저장됩니다)', padding=10)
            form.pack(fill='x', pady=8)
            self.vars = {}
            fields = [('OpenAlex API 키', 'openalex_key', True), ('OpenAI API 키', 'openai_key', True),
                      ('OpenAI 모델', 'model', False), ('Notion 통합 토큰 (선택)', 'notion_token', True),
                      ('Notion 상위 페이지 URL/ID (선택)', 'notion_page', False), ('최근 논문 범위 (일)', 'days', False)]
            for row, (label, key, secret) in enumerate(fields):
                ttk.Label(form, text=label).grid(row=row, column=0, sticky='w', pady=4)
                var = tk.StringVar(value=str(self.config_data[key]))
                self.vars[key] = var
                ttk.Entry(form, textvariable=var, show='*' if secret else '', width=65).grid(row=row, column=1, sticky='ew', padx=10)
            form.columnconfigure(1, weight=1)
            opts = ttk.Frame(body)
            opts.pack(fill='x')
            self.download = tk.BooleanVar(value=self.config_data['download_pdf'])
            self.auto = tk.BooleanVar(value=self.config_data['automatic'])
            ttk.Checkbutton(opts, text='자동 수집 시 PDF 저장 (수동 추천은 항상 저장)', variable=self.download).pack(side='left')
            ttk.Checkbutton(opts, text='자정 자동 수집 (이 창을 켜둬야 동작)', variable=self.auto, command=self.auto_changed).pack(side='left', padx=18)
            buttons = ttk.Frame(body)
            buttons.pack(fill='x', pady=12)
            self.save_btn = ttk.Button(buttons, text='설정 저장', command=self.save)
            self.save_btn.pack(side='left')
            self.run_btn = ttk.Button(buttons, text='새 논문 추천 + 다운로드 (F5)', command=self.start)
            self.run_btn.pack(side='left', padx=8)
            self.bind('<F5>', lambda event: self.start())
            ttk.Button(buttons, text='저장 폴더 열기', command=self.open_folder).pack(side='left')
            ttk.Button(buttons, text='키 발급·노션 연결 안내', command=self.help).pack(side='left', padx=8)
            ttk.Label(body, text='주목도는 발행 경과일을 고려한 인용 수와 주제 적합도입니다. SNS 언급량·조회수는 측정하지 않습니다.').pack(anchor='w')
            ttk.Label(body, text='요약은 초록 기반입니다. 한국어 데이터 수록 범위 때문에 매일 1편을 확보하지 못할 수 있습니다.').pack(anchor='w')
            self.status = tk.StringVar(value='설정 저장 → 새 논문 추천 또는 F5 순서로 시작하세요.')
            ttk.Label(body, textvariable=self.status).pack(anchor='w', pady=8)
            self.log_box = scrolledtext.ScrolledText(body, height=13, wrap='word', font=('Malgun Gothic', 10))
            self.log_box.pack(fill='both', expand=True)
            self.log('저장 위치: ' + str(core.HOME))
            self.protocol('WM_DELETE_WINDOW', self.close)
            self.after(200, self.poll)
            self.after(1000, self.schedule)

        def log(self, text):
            self.log_box.insert('end', f'[{core.now():%m-%d %H:%M:%S}] {text}\n')
            self.log_box.see('end')

        def save(self):
            if self.busy:
                return False
            try:
                config = {key: var.get().strip() for key, var in self.vars.items()}
                config['days'] = int(config['days'])
                if not 30 <= config['days'] <= 1825:
                    raise ValueError('검색 기간은 30~1825일 사이로 입력하세요.')
                if config['notion_page']:
                    core.page_id(config['notion_page'])
                if bool(config['notion_token']) != bool(config['notion_page']):
                    raise ValueError('노션 토큰과 상위 페이지 주소를 모두 입력하거나 둘 다 비워두세요.')
                config.update(download_pdf=self.download.get(), automatic=self.auto.get())
                core.save_config(config)
                self.config_data = config
                self.log('설정 저장 완료')
                return True
            except Exception as error:
                messagebox.showerror('설정 오류', core.safe_error(error))
                return False

        def auto_changed(self):
            if self.save():
                self.last_day, self.last_attempt = None, 0

        def start(self, manual=True):
            if self.busy or not self.save():
                return
            if not self.config_data['openalex_key'] or not self.config_data['openai_key']:
                messagebox.showinfo('API 키 필요', 'OpenAlex와 OpenAI API 키를 먼저 입력하세요. ChatGPT 구독과 API 요금은 별도입니다.')
                return
            self.busy = True
            self.run_btn.configure(state='disabled')
            self.save_btn.configure(state='disabled')
            self.last_day, self.last_attempt = core.now().date(), time.monotonic()
            self.status.set('검색·요약 중입니다. 몇 분 걸릴 수 있습니다.')
            config = dict(self.config_data)
            def worker():
                folder = None
                try:
                    folder = core.run(config, log=lambda text: self.events.put(('log', text)), manual=manual)
                except Exception as error:
                    self.events.put(('log', core.safe_error(error)))
                finally:
                    self.events.put(('done', str(folder) if manual and folder else None))
            threading.Thread(target=worker, daemon=True).start()

        def poll(self):
            try:
                while True:
                    kind, text = self.events.get_nowait()
                    if kind == 'log':
                        self.log(text)
                    else:
                        self.busy = False
                        self.run_btn.configure(state='normal')
                        self.save_btn.configure(state='normal')
                        self.status.set('작업 종료. 아래 기록에서 각 언어 저장·노션 전송 결과를 확인하세요.')
                        if text:
                            self.open_folder(Path(text))
            except queue.Empty:
                pass
            self.after(200, self.poll)

        def schedule(self):
            if self.auto.get() and not self.busy and self.config_data['openalex_key'] and self.config_data['openai_key']:
                if self.last_day != core.now().date() or time.monotonic() - self.last_attempt >= 900:
                    self.start(manual=False)
            self.after(10000, self.schedule)

        def open_folder(self, folder=None):
            folder = folder or core.HOME
            folder.mkdir(parents=True, exist_ok=True)
            if os.name == 'nt':
                os.startfile(str(folder))
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(folder)])
            else:
                subprocess.Popen(['xdg-open', str(folder)])

        def help(self):
            messagebox.showinfo('시작 안내',
                '1. OpenAlex: openalex.org/settings/api 에서 API 키 발급\n'
                '2. OpenAI: platform.openai.com/api-keys 에서 API 키 발급\n'
                '3. Notion: notion.so/profile/integrations 에서 내부 통합 생성\n'
                '4. 빈 상위 페이지에 통합을 연결하고 그 페이지 URL 입력\n'
                '5. 설정 저장 → 새 논문 추천 또는 F5\n\n'
                '연결된 페이지 아래에 표 데이터베이스를 자동 생성합니다.\n'
                '자정 자동 수집은 이 창과 PC를 켜두어야 동작합니다.\n'
                '노트북 절전 상태에서는 실행되지 않습니다.\n'
                'API 키는 config.json에 평문으로 저장됩니다. 공유하지 마세요.')
            webbrowser.open('https://openalex.org/settings/api')

        def close(self):
            if self.busy and not messagebox.askyesno('작업 중', '수집 작업이 진행 중입니다. 닫으면 작업이 중단됩니다. 종료할까요?'):
                return
            self.destroy()
    App().mainloop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true', help='저장한 설정으로 한 번 수집')
    args = parser.parse_args()
    if args.once:
        core.run(core.load_config())
    else:
        desktop()
