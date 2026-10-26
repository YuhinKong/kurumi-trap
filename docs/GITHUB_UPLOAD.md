# 上传到GitHub

当前项目已初始化本地Git仓库，但整理环境的目录写入限制阻止了首次提交。个人配置、.venv、data、.local、密钥文件和原始测试输出均被忽略。没有代你创建远程仓库或上传任何内容。

## 推荐：GitHub Desktop

1. 安装并登录GitHub Desktop。
2. File → Add local repository，选择当前项目根目录。
3. 查看Changes，填写提交说明后点击Commit to main完成首次提交。提交内容应为源码、测试、示例配置及文档；不要手动强制加入被忽略的运行数据。
4. 点击Publish repository，仓库名可用stock-monitor-agent。按自己的意愿选择公开或私有，再确认发布。
5. 发布后打开GitHub的Actions页面，查看Windows/Python3.13测试结果。

不需要上传整个.venv或行情数据库。你本机正在运行的软件仍使用原有配置和数据，发布源码不影响它。

## 使用源码ZIP

解压源码ZIP，在GitHub新建仓库，选择Add file → Upload files，上传解压后的项目文件与目录。不要只把ZIP本身上传作为源码。

浏览器拖拽可能遗漏点开头的文件夹；请确认.github/workflows、.gitignore和.gitattributes也在仓库中。需要完整保留这些文件时优先用GitHub Desktop。

## 发布前的仓库设置

尚未代你选择开源许可证。若希望允许他人按特定条款使用源码，请由仓库所有者自行选择许可证；不要将依赖包许可证当作本项目授权。

项目的行情数据来自外部公开接口，源码仓库不附带历史行情数据库。以后新增通知地址或其他敏感配置，继续通过环境变量管理，不要提交.env或secrets.toml。
