# 清除 Git 仓库的提交历史记录

本指南将帮助你清除 Git 远程仓库的所有提交历史，创建一个全新的仓库起点。

## 操作步骤

### 1. 克隆仓库
将远程仓库克隆到本地：
```bash
git clone git@github.com:Wolf-Wang/Junk-Cleaner.git
```

### 2. 进入仓库目录
```bash
cd Junk-Cleaner
```

### 3. 创建新的孤立分支
创建一个名为 'master' 的新分支，该分支没有任何提交历史：
```bash
git checkout --orphan master
```

### 4. 暂存所有文件
将当前目录下的所有文件添加到暂存区：
```bash
git add .
```

### 5. 创建初始提交
创建一个新的初始提交：
```bash
git commit -m "Initial commit: remove commit history"
```

### 6. 强制推送
将新建的分支强制推送到远程仓库：
```bash
git push -f origin master
```

### 7. 完成清理
1. 访问 GitHub 仓库设置页面
2. 进入 `Settings` > `General` > `Default branch`
3. 将新的 `master` 分支设置为默认分支
4. 删除原有的旧分支
5. 如有需要，可以重命名当前分支

## 注意事项
- 此操作不可逆，请确保你真的需要清除所有历史记录
- 执行前请备份重要数据
- 如果是团队项目，请提前通知所有协作者
