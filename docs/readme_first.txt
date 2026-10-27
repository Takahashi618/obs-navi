OBSナビ {VERSION} テスト版　はじめにお読みください（README）

テストにご協力いただき、ありがとうございます。
OBSナビは、スクリーンリーダー（PC-Talker・NVDA）で OBS Studio を操作するための道具です。


■ このフォルダの中身

ファイルが13、フォルダが2つあります。名前は、文字化けしないようにすべて英字にしてあります。日本語の書類は名前の最後に (Japanese)、英語の書類は (English) が付いています。

・OBSNavi.exe は、OBSナビ本体です。これを起動します。
・README (Japanese).txt は、このファイル（はじめにお読みください）です。
・Manual (Japanese).html と Manual (Japanese).txt は、使い方の説明（マニュアル）です。中身は同じです。
・Testing Guide (Japanese).html と Testing Guide (Japanese).txt は、確かめてほしいことと知らせ方（テストのお願い）です。中身は同じです。
・README (English).txt、Manual (English).html と .txt、Testing Guide (English).html と .txt の5つは、上の3つの英語版です。
・LICENSE.txt は、ライセンス（GNU GPL 第3版）の全文です。英語です。
・THIRD-PARTY-NOTICES.txt は、同梱している部品とそのライセンスです。
・_internal フォルダは、OBSナビが動くのに必要な部品です。中は触らないでください。
・source フォルダは、OBSナビのソースコードです。使うだけなら要りません。

html の文書はブラウザで開くと見出しで移動でき、txt の文書はメモ帳などで上から順に読めます。
OBSナビを起動すると、設定ファイル obs_navi_config.json がこのフォルダに増えます。


■ 最初の3歩

1. このフォルダを、「ドキュメント」など自分が書き込めるフォルダに置きます。「Program Files」の中には置かないでください。
2. OBS Studio を起動し、「ツール」メニューの「WebSocket サーバー設定」で「WebSocketサーバーを有効にする」をオンにして「OK」を押します。詳しくはマニュアルの「3. 準備と起動」にあります。
3. OBSNavi.exe を起動します。「OBSナビ バージョン {VERSION} の状態」に続けて「OBSに接続しました」と読めば準備完了です。

「Windows によって PC が保護されました」という画面が出たときは、Tab キーで「詳細情報」へ移って Enter を押し、さらに Tab キーで「実行」ボタンへ移って Enter を押します。


■ テストの前に

OBS のシーンコレクションとプロファイルを、エクスポートしておいてください。OBSナビはシーンやソースを削除でき、削除は元に戻せません。手順は「テストのお願い」の「2. テストの前に」にあります。

OBSナビは配信を開始できます。配信を試すときは、視聴者に見られても困らない状態で行ってください。


■ 表示の言語

OBSナビは、Windows の表示言語が日本語なら日本語、それ以外なら英語で起動します。変えるときは、「ツール」メニューの「表示の言語 (Language)」を選びます。


■ 終了のしかた

Alt+F4 で終了します。Escape キーでは終了しません。


以上です。
