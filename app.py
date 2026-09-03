
import sys,time,tempfile
from pathlib import Path
from PySide6.QtCore import Qt,QThread,Signal,QTimer
from PySide6.QtGui import QFont,QAction
from PySide6.QtWidgets import *
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from engine import collect_quotes,find_opportunities,find_basis,historical_funding,classic_from_live
from database import RadarDB
from settings import SettingsStore
from assistant_client import ask_openai,save_api_key,get_api_key
from live_market import LiveMarket
from exchange_api import save_credentials,credentials_present,load_balance,FIELDS
import updater

APP_DIR=Path(__file__).resolve().parent
settings=SettingsStore(str(APP_DIR/"settings.json"))
db=RadarDB(str(APP_DIR/"data"/"radar.db"))

class ScanWorker(QThread):
    done=Signal(object,object,object,object);failed=Signal(str)
    def run(self):
        try:
            q,e=collect_quotes(settings.get("assets"),settings.get("exchanges"))
            ops=find_opportunities(q,settings.get("taker_fees"),float(settings.get("slippage_total")))
            basis=find_basis(q,settings.get("taker_fees"),float(settings.get("slippage_total")))
            db.save(ops,basis,[])
            self.done.emit(q,ops,basis,e)
        except Exception as ex:self.failed.emit(str(ex))

class BalanceWorker(QThread):
    done=Signal(str,object);failed=Signal(str,str)
    def __init__(self,e):super().__init__();self.e=e
    def run(self):
        try:self.done.emit(self.e,load_balance(self.e))
        except Exception as x:self.failed.emit(self.e,str(x))

class AIWorker(QThread):
    done=Signal(str);failed=Signal(str)
    def __init__(self,q,c,m):super().__init__();self.q=q;self.c=c;self.m=m
    def run(self):
        try:self.done.emit(ask_openai(self.q,self.c,self.m))
        except Exception as e:self.failed.emit(str(e))

class HistWorker(QThread):
    done=Signal(object);failed=Signal(str)
    def __init__(self,op):super().__init__();self.op=op
    def run(self):
        try:
            out={}
            for e in {self.op.long_exchange,self.op.short_exchange}:
                if e!="MEXC":out[e]=historical_funding(e,self.op.asset,7)
            self.done.emit(out)
        except Exception as e:self.failed.emit(str(e))

class ApiDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle("API бирж — только локальное хранение");self.resize(660,560)
        v=QVBoxLayout(self)
        note=QLabel("Ключи сохраняются в системном хранилище Windows через keyring и не записываются в settings.json. "
                    "Создавай ключи БЕЗ разрешения на вывод средств. Для v0.5 достаточно Read; Trading можно добавить позже.")
        note.setWordWrap(True);v.addWidget(note)
        self.tabs=QTabWidget();v.addWidget(self.tabs);self.ed={}
        for e in settings.get("exchanges"):
            w=QWidget();f=QFormLayout(w);self.ed[e]={}
            for field in FIELDS[e]:
                x=QLineEdit();x.setEchoMode(QLineEdit.Password)
                x.setPlaceholderText("уже сохранено" if credentials_present(e) else field)
                self.ed[e][field]=x;f.addRow(field,x)
            b=QPushButton("Сохранить");b.clicked.connect(lambda _,ex=e:self.save_one(ex));f.addRow(b)
            self.tabs.addTab(w,e)
        bb=QDialogButtonBox(QDialogButtonBox.Close);bb.rejected.connect(self.reject);v.addWidget(bb)
    def save_one(self,e):
        vals={k:x.text() for k,x in self.ed[e].items()}
        try:
            save_credentials(e,vals);QMessageBox.information(self,"API",f"{e}: сохранено в системном хранилище.")
        except Exception as x:QMessageBox.warning(self,"API",str(x))

class SettingsDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle("Настройки");self.resize(540,560)
        v=QVBoxLayout(self);f=QFormLayout()
        self.cap=QDoubleSpinBox();self.cap.setRange(10,1e8);self.cap.setDecimals(0);self.cap.setValue(settings.get("capital"))
        self.ui=QSpinBox();self.ui.setRange(100,2000);self.ui.setSuffix(" мс");self.ui.setValue(settings.get("live_ui_ms"))
        self.age=QSpinBox();self.age.setRange(100,10000);self.age.setSuffix(" мс");self.age.setValue(settings.get("max_quote_age_ms"))
        self.edge=QDoubleSpinBox();self.edge.setRange(0,10);self.edge.setDecimals(3);self.edge.setSuffix(" %");self.edge.setValue(settings.get("classic_min_net_edge_pct"))
        self.strong=QDoubleSpinBox();self.strong.setRange(0,10);self.strong.setDecimals(3);self.strong.setSuffix(" %");self.strong.setValue(settings.get("classic_strong_net_edge_pct"))
        f.addRow("Расчётный капитал, $",self.cap);f.addRow("Обновление таблицы",self.ui);f.addRow("Макс. возраст котировки",self.age)
        f.addRow("Минимальный NET edge",self.edge);f.addRow("Сильный сигнал от",self.strong)
        self.fees={}
        for e in settings.get("exchanges"):
            b=QDoubleSpinBox();b.setRange(0,2);b.setDecimals(4);b.setSuffix(" %");b.setValue(settings.get("taker_fees")[e]*100)
            self.fees[e]=b;f.addRow(f"{e} taker fee",b)
        self.api=QLineEdit();self.api.setEchoMode(QLineEdit.Password);self.api.setPlaceholderText("сохранён" if get_api_key() else "OpenAI API key")
        self.model=QLineEdit(settings.get("openai_model"));self.upurl=QLineEdit(settings.get("update_manifest_url"))
        f.addRow("OpenAI API",self.api);f.addRow("AI model",self.model);f.addRow("Канал обновлений",self.upurl)
        v.addLayout(f)
        bb=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);bb.accepted.connect(self.save);bb.rejected.connect(self.reject);v.addWidget(bb)
    def save(self):
        settings.set("capital",self.cap.value());settings.set("live_ui_ms",self.ui.value());settings.set("max_quote_age_ms",self.age.value())
        settings.set("classic_min_net_edge_pct",self.edge.value());settings.set("classic_strong_net_edge_pct",self.strong.value())
        settings.set("taker_fees",{e:b.value()/100 for e,b in self.fees.items()})
        settings.set("openai_model",self.model.text().strip() or "gpt-5");settings.set("update_manifest_url",self.upurl.text().strip())
        if self.api.text().strip():save_api_key(self.api.text())
        self.accept()

class Main(QMainWindow):
    def __init__(self):
        super().__init__();self.setWindowTitle("Arbitrage Radar v0.5.2");self.resize(1720,930)
        self.ops=[];self.basis=[];self.classic=[];self.selected=None;self.signal_seen={};self.balance_workers=[]
        self.market=LiveMarket(settings.get("assets"));self.market.start()
        self.build()
        self.ui_timer=QTimer(self);self.ui_timer.timeout.connect(self.refresh_live_classic);self.reset_ui_timer()
        self.slow_timer=QTimer(self);self.slow_timer.timeout.connect(self.scan_now);self.slow_timer.start(60000)
        QTimer.singleShot(500,self.scan_now)
    def closeEvent(self,e):
        self.market.stop();super().closeEvent(e)
    def reset_ui_timer(self):
        self.ui_timer.setInterval(int(settings.get("live_ui_ms")));self.ui_timer.start()
    def build(self):
        mb=self.menuBar()
        a=QAction("Настройки",self);a.triggered.connect(self.open_settings);mb.addAction(a)
        ap=QAction("API бирж",self);ap.triggered.connect(lambda:ApiDialog(self).exec());mb.addAction(ap)
        up=QAction("Обновления",self);up.triggered.connect(self.update_dialog);mb.addAction(up)
        root=QWidget();self.setCentralWidget(root);v=QVBoxLayout(root)
        top=QHBoxLayout();title=QLabel("ARBITRAGE RADAR  v0.5.2");f=QFont();f.setPointSize(17);f.setBold(True);title.setFont(f);top.addWidget(title)
        self.live=QLabel("● LIVE START");top.addWidget(self.live);top.addStretch()
        b=QPushButton("API / балансы");b.clicked.connect(self.show_balances);top.addWidget(b)
        s=QPushButton("Обновить funding");s.clicked.connect(self.scan_now);top.addWidget(s);v.addLayout(top)
        tabs=QTabWidget();v.addWidget(tabs)

        # Classic - primary
        cla=QWidget();cv=QVBoxLayout(cla)
        self.wsstatus=QLabel();self.wsstatus.setWordWrap(True);cv.addWidget(self.wsstatus)
        info=QLabel("LIVE Classic Arbitrage: BUY по ask на дешёвой бирже + SELL по bid на дорогой. "
                    "Таблица перерисовывается каждые ~250 мс, а WebSocket-кэш обновляется по мере прихода биржевых событий.")
        info.setWordWrap(True);cv.addWidget(info)
        self.ct=QTableWidget(0,14);self.ct.setHorizontalHeaderLabels(
            ["Актив","BUY","SELL","Buy ask","Sell bid","Gross","Cost","NET","P&L","Age","Живёт","Ask qty","Bid qty","ЧТО ДЕЛАТЬ"])
        self.ct.setEditTriggers(QAbstractItemView.NoEditTriggers);self.ct.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.ct.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents);self.ct.horizontalHeader().setStretchLastSection(True)
        cv.addWidget(self.ct);tabs.addTab(cla,"★ Classic Arbitrage LIVE")

        # Funding
        fund=QWidget();fv=QVBoxLayout(fund);self.summary=QLabel();fv.addWidget(self.summary);sp=QSplitter(Qt.Horizontal)
        self.table=QTableWidget(0,11);self.table.setHorizontalHeaderLabels(
            ["Актив","LONG","SHORT","Gross APR","Cost RT","BE ч","Gap","Net","P&L","Статус","ЧТО ДЕЛАТЬ"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.select_op);self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents);sp.addWidget(self.table)
        right=QWidget();rv=QVBoxLayout(right);rv.addWidget(QLabel("AI-АССИСТЕНТ"));self.ctx=QLabel("Выберите связку");self.ctx.setWordWrap(True);rv.addWidget(self.ctx)
        self.chart=FigureCanvas(Figure(figsize=(5,3)));rv.addWidget(self.chart)
        h=QPushButton("Загрузить 7 дней funding");h.clicked.connect(self.load_hist);rv.addWidget(h)
        p=QPushButton("Добавить в PAPER");p.clicked.connect(self.paper_add);rv.addWidget(p)
        self.chat=QTextEdit();self.chat.setReadOnly(True);rv.addWidget(self.chat);self.q=QLineEdit();self.q.returnPressed.connect(self.ask);rv.addWidget(self.q)
        ab=QPushButton("Спросить");ab.clicked.connect(self.ask);rv.addWidget(ab);sp.addWidget(right);sp.setSizes([1100,500]);fv.addWidget(sp);tabs.addTab(fund,"Funding Arbitrage")

        bas=QWidget();bv=QVBoxLayout(bas);self.bt=QTableWidget(0,9);self.bt.setHorizontalHeaderLabels(
            ["Биржа","Актив","Spot ask","Perp bid","Basis","Funding APR","Cost RT","Net basis","ЧТО ДЕЛАТЬ"])
        self.bt.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);bv.addWidget(self.bt);tabs.addTab(bas,"Spot ↔ Perpetual Basis")

        pap=QWidget();pv=QVBoxLayout(pap);self.pt=QTableWidget(0,9);self.pt.setHorizontalHeaderLabels(
            ["ID","Открыта","Актив","LONG","SHORT","Капитал","Entry APR","Статус","Realized"])
        self.pt.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);pv.addWidget(self.pt);tabs.addTab(pap,"PAPER Portfolio")
        self.setStatusBar(QStatusBar())

    def refresh_live_classic(self):
        snap,status=self.market.snapshot()
        self.wsstatus.setText(" | ".join(f"{e}: {status.get(e,'—')}" for e in settings.get("exchanges")))
        ops,self.signal_seen=classic_from_live(
            snap,settings.get("taker_fees"),settings.get("slippage_total"),
            settings.get("classic_min_net_edge_pct"),settings.get("classic_strong_net_edge_pct"),
            settings.get("max_quote_age_ms"),self.signal_seen)
        self.classic=ops;cap=settings.get("capital")
        self.ct.setRowCount(len(ops))
        for r,o in enumerate(ops):
            vals=[o.asset,o.buy_exchange,o.sell_exchange,f"{o.buy_ask:.8g}",f"{o.sell_bid:.8g}",
                  f"{o.gross_spread_pct:+.4f}%",f"{o.est_total_cost*100:.3f}%",f"{o.net_edge_pct:+.4f}%",
                  f"${o.net_pnl(cap):+,.2f}",f"{o.age_ms} ms",f"{o.signal_lifetime_s:.2f}s",
                  f"{o.buy_ask_qty:.6g}",f"{o.sell_bid_qty:.6g}",o.action_comment]
            for c,x in enumerate(vals):self.ct.setItem(r,c,QTableWidgetItem(str(x)))
        fresh=sum(1 for q in snap.values() if int(time.time()*1000)-q.recv_ts_ms<=settings.get("max_quote_age_ms"))
        self.live.setText(f"● LIVE BBO {fresh}/{len(snap)}")

    def open_settings(self):
        d=SettingsDialog(self)
        if d.exec():self.reset_ui_timer()
    def scan_now(self):
        if hasattr(self,"scan") and self.scan and self.scan.isRunning():return
        self.scan=ScanWorker();self.scan.done.connect(self.scan_done);self.scan.failed.connect(self.scan_failed);self.scan.start()
    def scan_failed(self,msg):
        self.statusBar().showMessage("Funding refresh error: "+msg,15000)
        self.live.setText("● LIVE Classic / funding error")

    def scan_done(self,quotes,ops,basis,errors):
        self.ops=ops;self.basis=basis;cap=settings.get("capital");hold=settings.get("hold_hours")
        self.summary.setText(f"Funding связок: {len(ops)} | Basis: {len(basis)} | Ошибки: {len(errors)} | ${cap:,.0f}/{hold:g}ч")
        self.table.setRowCount(len(ops))
        for r,o in enumerate(ops):
            net=o.net_return_pct(hold);pnl=o.net_pnl(cap,hold);st=o.status(settings.get("min_gross_apr_pct"),settings.get("max_break_even_hours"))
            if net<0:comment="🔴 НЕ ТОРГОВАТЬ — на выбранном горизонте расходы выше funding"
            elif o.break_even_hours>settings.get("max_break_even_hours"):comment=f"🟡 ЖДАТЬ — break-even {o.break_even_hours:.1f}ч слишком долгий"
            else:comment=f"🟢 РАССМОТРЕТЬ — LONG {o.long_exchange}, SHORT {o.short_exchange}; нужна проверка устойчивости funding"
            vals=[o.asset,o.long_exchange,o.short_exchange,f"{o.gross_apr_pct:.2f}%",f"{o.est_total_cost*100:.3f}%",f"{o.break_even_hours:.1f}",
                  f"{o.entry_price_gap_pct:+.3f}%",f"{net:+.3f}%",f"${pnl:+,.2f}",st,comment]
            for c,x in enumerate(vals):self.table.setItem(r,c,QTableWidgetItem(str(x)))
        self.bt.setRowCount(len(basis))
        for r,b in enumerate(basis):
            if b.simple_net_basis_pct<=0:comment="🔴 НЕ ТОРГОВАТЬ — basis не перекрывает расходы"
            else:comment="🟡 ИЗУЧИТЬ — текущий basis положительный, но нужен расчёт удержания и funding"
            vals=[b.exchange,b.asset,f"{b.spot_ask:.8g}",f"{b.perp_bid:.8g}",f"{b.basis_pct:+.3f}%",f"{b.funding_apr_pct:+.2f}%",
                  f"{b.est_total_cost*100:.3f}%",f"{b.simple_net_basis_pct:+.3f}%",comment]
            for c,x in enumerate(vals):self.bt.setItem(r,c,QTableWidgetItem(str(x)))
        self.refresh_paper()

    def show_balances(self):
        dlg=QDialog(self);dlg.setWindowTitle("API / балансы");dlg.resize(700,520);v=QVBoxLayout(dlg)
        t=QTableWidget(0,4);t.setHorizontalHeaderLabels(["Биржа","API","Статус","Ненулевые балансы"]);t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);v.addWidget(t)
        t.setRowCount(len(settings.get("exchanges")));workers=[]
        for r,e in enumerate(settings.get("exchanges")):
            t.setItem(r,0,QTableWidgetItem(e));present=credentials_present(e);t.setItem(r,1,QTableWidgetItem("есть" if present else "нет"))
            t.setItem(r,2,QTableWidgetItem("проверяю…" if present else "откройте меню API бирж"))
            if present:
                w=BalanceWorker(e);workers.append(w)
                w.done.connect(lambda ex,rows,table=t:self._balance_ok(table,ex,rows))
                w.failed.connect(lambda ex,msg,table=t:self._balance_fail(table,ex,msg));w.start()
        self.balance_workers.extend(workers)
        b=QPushButton("Настроить API");b.clicked.connect(lambda:(ApiDialog(self).exec()));v.addWidget(b);dlg.exec()
    def _row_for_exchange(self,t,e):
        for r in range(t.rowCount()):
            if t.item(r,0) and t.item(r,0).text()==e:return r
        return -1
    def _balance_ok(self,t,e,rows):
        r=self._row_for_exchange(t,e)
        if r<0:return
        t.setItem(r,2,QTableWidgetItem("✅ READ OK"))
        s=", ".join(f"{c}: {avail:g}" for c,total,avail in rows[:8]) or "нулевые/не возвращены"
        t.setItem(r,3,QTableWidgetItem(s))
    def _balance_fail(self,t,e,msg):
        r=self._row_for_exchange(t,e)
        if r>=0:t.setItem(r,2,QTableWidgetItem("❌ "+msg[:90]))

    def select_op(self):
        rows=self.table.selectionModel().selectedRows()
        if not rows:return
        i=rows[0].row()
        if i>=len(self.ops):return
        self.selected=self.ops[i];o=self.selected
        self.ctx.setText(f"{o.asset}: LONG {o.long_exchange} / SHORT {o.short_exchange}\nGross {o.gross_apr_pct:.2f}% APR | BE {o.break_even_hours:.1f}ч")
        self.draw_history()
    def draw_history(self):
        if not self.selected:return
        rows=db.history(self.selected.asset,self.selected.long_exchange,self.selected.short_exchange,500)
        fig=self.chart.figure;fig.clear();ax=fig.add_subplot(111)
        if rows:ax.plot([x[1] for x in rows]);ax.set_ylabel("Gross APR %");ax.grid(True,alpha=.2)
        self.chart.draw()
    def load_hist(self):
        if not self.selected:return
        self.hw=HistWorker(self.selected);self.hw.done.connect(lambda d:self.chat.append("\n7 дней funding:\n"+str({k:len(v) for k,v in d.items()})))
        self.hw.failed.connect(lambda e:self.chat.append("Ошибка: "+e));self.hw.start()
    def paper_add(self):
        if self.selected:db.open_paper(self.selected,settings.get("capital"));self.refresh_paper()
    def refresh_paper(self):
        rows=db.paper_rows();self.pt.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,x in enumerate(row):self.pt.setItem(r,c,QTableWidgetItem(str(x)))
    def ask(self):
        q=self.q.text().strip()
        if not q:return
        ctx="Нет выбранной funding-связки" if not self.selected else str(self.selected)
        self.chat.append("Вы: "+q);self.q.clear();self.aiw=AIWorker(q,ctx,settings.get("openai_model"))
        self.aiw.done.connect(lambda x:self.chat.append("\nAI: "+x+"\n"));self.aiw.failed.connect(lambda x:self.chat.append("\nОшибка AI: "+x+"\n"));self.aiw.start()

    def update_dialog(self):
        dlg=QDialog(self);dlg.setWindowTitle("Обновления Arbitrage Radar");dlg.resize(620,360)
        v=QVBoxLayout(dlg)
        cur=updater.current_version(APP_DIR)
        lbl=QLabel(f"Текущая версия: {cur}\nКанал обновлений:\n{settings.get('update_manifest_url') or 'не настроен'}")
        lbl.setWordWrap(True);v.addWidget(lbl)
        notes=QTextEdit();notes.setReadOnly(True);notes.setPlaceholderText("Здесь появится информация о релизе.");v.addWidget(notes)
        row=QHBoxLayout()
        check=QPushButton("Проверить обновления онлайн")
        local=QPushButton("Установить обновление из ZIP")
        row.addWidget(check);row.addWidget(local);v.addLayout(row)
        close=QDialogButtonBox(QDialogButtonBox.Close);close.rejected.connect(dlg.reject);v.addWidget(close)

        def do_check():
            url=settings.get("update_manifest_url","").strip()
            if not url:
                QMessageBox.information(dlg,"Обновления","Канал обновлений не настроен.")
                return
            check.setEnabled(False);check.setText("Проверяю…")
            QApplication.processEvents()
            try:
                m=updater.fetch_manifest(url)
                remote=str(m.get("version","0.0.0"));notes.setPlainText(m.get("notes",""))
                if updater.parse_version(remote)<=updater.parse_version(cur):
                    QMessageBox.information(dlg,"Обновления",f"Установлена актуальная версия {cur}.")
                    return
                answer=QMessageBox.question(
                    dlg,"Найдено обновление",
                    f"Доступна версия {remote}.\n\n{m.get('notes','')}\n\nСкачать и установить?",
                    QMessageBox.Yes|QMessageBox.No)
                if answer!=QMessageBox.Yes:return
                zip_url=m.get("zip_url","");sha=m.get("sha256","")
                if not zip_url:raise RuntimeError("В update.json нет zip_url.")
                tmp=Path(tempfile.gettempdir())/f"ArbitrageRadar_{remote}.zip"
                updater.download(zip_url,tmp)
                updater.verify_sha256(tmp,sha)
                updater.stage_update(tmp,APP_DIR)
                QApplication.quit()
            except Exception as e:
                QMessageBox.warning(dlg,"Ошибка обновления",str(e))
            finally:
                check.setEnabled(True);check.setText("Проверить обновления онлайн")

        def do_local():
            p,_=QFileDialog.getOpenFileName(dlg,"Выберите ZIP обновления","","ZIP (*.zip)")
            if p:
                try:
                    updater.stage_update(p,APP_DIR);QApplication.quit()
                except Exception as e:QMessageBox.warning(dlg,"Обновление",str(e))

        check.clicked.connect(do_check);local.clicked.connect(do_local)
        dlg.exec()

if __name__=="__main__":
    app=QApplication(sys.argv);w=Main();w.show();sys.exit(app.exec())
