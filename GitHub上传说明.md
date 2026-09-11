# 上传到 GitHub 与开启在线网站

本项目已经整理成标准 Git 仓库结构，可以直接上传到 GitHub。

---

## 一、仓库里会包含什么

上传后会包含：

- 网站入口 `index.html`；
- 样式与前端逻辑 `assets/`；
- 抓取、分析和建站脚本 `crawler/`；
- 已抓取的数据 `data/`；
- Windows 快捷脚本；
- 使用说明与项目说明；
- GitHub Pages 自动部署工作流；
- GitHub Actions 自动检查工作流。

不会上传：

- Python 缓存；
- 自测临时目录；
- 浏览器预览文件；
- 每日更新日志；
- `.env` 等本地敏感配置。

---

## 二、方式 A：用 Git 命令上传

在 GitHub 网页上先新建一个空仓库，例如：

```
power-market-radar
```

不要勾选自动创建 README、`.gitignore` 或 License，因为你本地已经准备好了。

然后在本项目目录执行：

```
git remote add origin https://github.com/你的用户名/power-market-radar.git
git push -u origin main
```

如果使用 SSH：

```
git remote add origin git@github.com:你的用户名/power-market-radar.git
git push -u origin main
```

第一次推送后会要求登录 GitHub。推荐安装 GitHub CLI，或在 Windows
凭据管理器中登录 GitHub 账号。

---

## 三、方式 B：用 GitHub 网页上传

1. 在 GitHub 新建空仓库；
2. 进入仓库页面，点击 **Add file → Upload files**；
3. 把本项目中的全部文件拖进去；
4. 确认没有上传 `__pycache__`、`_preview`、`_selftest_tmp`、`logs`；
5. 提交到 `main` 分支。

网页上传适合一次性使用。后续如果经常抓取和更新数据，建议使用 Git 命令或
GitHub Desktop。

---

## 四、开启 GitHub Pages 网站

上传完成后：

1. 打开仓库的 **Settings**；
2. 左侧选择 **Pages**；
3. 在 **Build and deployment → Source** 中选择 **GitHub Actions**；
4. 回到仓库的 **Actions** 页面，等待 `Deploy website to GitHub Pages` 完成；
5. 完成后会在 Actions 或 Pages 页面显示网站地址，通常形如：

```
https://你的用户名.github.io/power-market-radar/
```

以后每次把更新后的 `data/data.js` 和 `data/demo.js` 推送到 `main`，
网站都会自动重新部署。

---

## 五、更新数据后怎么同步

本地双击更新脚本后，会产生新的：

```
data/data.js
data/demo.js
data/papers.json
data/insights.json
data/meta.json
data/library.db
```

然后在项目目录执行：

```
git status
git add .
git commit -m "Update literature data"
git push
```

GitHub Pages 会自动发布最新数据。

---

## 六、建议的仓库设置

- 仓库名称：`power-market-radar`；
- 可见性：可以选择 Public，也可以 Private；
- 默认分支：`main`；
- Pages 来源：`GitHub Actions`；
- 不需要额外服务器、数据库或 API Key。

如果希望仓库公开但不想公开本地文献库 `data/library.db`，可以在 `.gitignore`
中加入：

```
data/library.db
```

网站只需要 `data/data.js` 和 `data/demo.js` 就能正常显示。`library.db`
只是本机继续增量抓取时使用的历史数据库。

