on run
    set bundlePath to POSIX path of (path to me)
    set projectPath to do shell script "/usr/bin/dirname " & quoted form of bundlePath
    set launcherPath to projectPath & "/启动.command"
    try
        do shell script "test -x " & quoted form of launcherPath
        with timeout of 180 seconds
            do shell script "/bin/sh " & quoted form of launcherPath & " --desktop"
        end timeout
    on error errorMessage number errorNumber
        display alert "Forever AI 启动未完成" message ("启动入口：" & launcherPath & return & "错误 " & errorNumber & "：" & errorMessage) as warning
    end try
end run
