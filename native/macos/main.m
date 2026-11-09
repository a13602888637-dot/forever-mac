#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#import <unistd.h>

@interface ForeverApp : NSObject <NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate>
@property(nonatomic,strong) NSWindow *window;
@property(nonatomic,strong) WKWebView *webView;
@property(nonatomic,strong) NSView *loadingView;
@property(nonatomic,strong) NSTextField *statusLabel;
@property(nonatomic,strong) NSProgressIndicator *progress;
@property(nonatomic,strong) NSTask *bootstrap;
@property(nonatomic,strong) NSURL *projectURL;
@property(nonatomic,strong) NSURL *serviceURL;
@property(nonatomic,strong) NSImage *appIcon;
@end

@implementation ForeverApp

- (NSString *)argumentAfter:(NSString *)key {
    NSArray *args = NSProcessInfo.processInfo.arguments;
    NSUInteger index = [args indexOfObject:key];
    return index != NSNotFound && index + 1 < args.count ? args[index + 1] : nil;
}
- (NSURL *)verificationDirectory {
    NSString *size = [self argumentAfter:@"--verify-size"] ?: @"default";
    NSCharacterSet *invalid = [[NSCharacterSet characterSetWithCharactersInString:@"0123456789x"] invertedSet];
    if ([size rangeOfCharacterFromSet:invalid].location != NSNotFound) size = @"default";
    return [self.projectURL URLByAppendingPathComponent:[@"outputs/v04/native-" stringByAppendingString:size] isDirectory:YES];
}


- (void)writeState:(NSString *)phase message:(NSString *)message {
    NSURL *directory = [NSProcessInfo.processInfo.arguments containsObject:@"--verify-native"] ? [self verificationDirectory] : [self.projectURL URLByAppendingPathComponent:@"data" isDirectory:YES];
    [[NSFileManager defaultManager] createDirectoryAtURL:directory withIntermediateDirectories:YES attributes:nil error:nil];
    NSDictionary *state = @{
        @"phase":phase, @"message":message ?: @"", @"pid":@(getpid()),
        @"window_visible":@(self.window.visible), @"window_number":@(self.window.windowNumber),
        @"url":self.webView.URL.absoluteString ?: self.serviceURL.absoluteString ?: @"",
        @"updated_at":@((long long)[NSDate.date timeIntervalSince1970])
    };
    NSData *data = [NSJSONSerialization dataWithJSONObject:state options:NSJSONWritingPrettyPrinted error:nil];
    [data writeToURL:[directory URLByAppendingPathComponent:@"native-window-state.json"] options:NSDataWritingAtomic error:nil];
}

- (void)setupMenu {
    NSMenu *menu = [[NSMenu alloc] init];
    NSMenuItem *appItem = [[NSMenuItem alloc] init];
    [menu addItem:appItem];
    NSMenu *appMenu = [[NSMenu alloc] initWithTitle:@"Forever"];
    [appMenu addItemWithTitle:@"关于 Forever" action:@selector(orderFrontStandardAboutPanel:) keyEquivalent:@""];
    [appMenu addItem:NSMenuItem.separatorItem];
    [appMenu addItemWithTitle:@"退出 Forever" action:@selector(terminate:) keyEquivalent:@"q"];
    appItem.submenu = appMenu;
    NSMenuItem *editItem = [[NSMenuItem alloc] initWithTitle:@"编辑" action:nil keyEquivalent:@""];
    NSMenu *edit = [[NSMenu alloc] initWithTitle:@"编辑"];
    [edit addItemWithTitle:@"撤销" action:@selector(undo:) keyEquivalent:@"z"];
    [edit addItem:NSMenuItem.separatorItem];
    [edit addItemWithTitle:@"剪切" action:@selector(cut:) keyEquivalent:@"x"];
    [edit addItemWithTitle:@"复制" action:@selector(copy:) keyEquivalent:@"c"];
    [edit addItemWithTitle:@"粘贴" action:@selector(paste:) keyEquivalent:@"v"];
    [edit addItemWithTitle:@"全选" action:@selector(selectAll:) keyEquivalent:@"a"];
    editItem.submenu = edit; [menu addItem:editItem];
    NSMenuItem *viewItem = [[NSMenuItem alloc] initWithTitle:@"显示" action:nil keyEquivalent:@""];
    NSMenu *view = [[NSMenu alloc] initWithTitle:@"显示"];
    NSMenuItem *reload = [[NSMenuItem alloc] initWithTitle:@"刷新" action:@selector(refresh:) keyEquivalent:@"r"];
    reload.target = self; [view addItem:reload];
    NSMenuItem *home = [[NSMenuItem alloc] initWithTitle:@"插件管理" action:@selector(goHome:) keyEquivalent:@"1"];
    home.target = self; [view addItem:home];
    viewItem.submenu = view; [menu addItem:viewItem];
    NSApp.mainMenu = menu;
}

- (NSTextField *)label:(NSString *)text size:(CGFloat)size color:(NSColor *)color {
    NSTextField *label = [NSTextField labelWithString:text];
    label.font = [NSFont systemFontOfSize:size weight:NSFontWeightMedium];
    label.textColor = color; label.alignment = NSTextAlignmentCenter;
    label.translatesAutoresizingMaskIntoConstraints = NO;
    return label;
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    NSURL *bundleURL = NSBundle.mainBundle.bundleURL;
    self.projectURL = [bundleURL URLByDeletingLastPathComponent];
    NSString *configured = [NSBundle.mainBundle objectForInfoDictionaryKey:@"ForeverAIProjectPath"];
    NSURL *entry = [self.projectURL URLByAppendingPathComponent:@"启动.command"];
    if (![[NSFileManager defaultManager] isExecutableFileAtPath:entry.path] && configured.length) {
        self.projectURL = [NSURL fileURLWithPath:configured isDirectory:YES];
    }
    self.appIcon = [[NSImage alloc] initWithContentsOfFile:[NSBundle.mainBundle pathForResource:@"ForeverAI" ofType:@"icns"]];
    NSApp.applicationIconImage = self.appIcon;
    [self setupMenu];
    NSRect screen = NSScreen.mainScreen.visibleFrame;
    CGFloat width = MIN(1320,NSWidth(screen)-48), height = MIN(900,NSHeight(screen)-60);
    if ([NSProcessInfo.processInfo.arguments containsObject:@"--verify-native"]) {
        NSArray *size = [[self argumentAfter:@"--verify-size"] componentsSeparatedByString:@"x"];
        if (size.count == 2) { width = MAX(900,MIN(2000,[size[0] doubleValue])); height = MAX(620,MIN(1500,[size[1] doubleValue])); }
    }
    self.window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,width,height)
        styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable
        backing:NSBackingStoreBuffered defer:NO];
    self.window.title = @"Forever";
    self.window.titlebarAppearsTransparent = YES;
    self.window.backgroundColor = [NSColor colorWithSRGBRed:.098 green:.102 blue:.114 alpha:1];
    self.window.appearance = [NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];
    self.window.minSize = NSMakeSize(MIN(900,width),MIN(620,height));
    self.window.releasedWhenClosed = NO;
    [self.window center];
    WKWebViewConfiguration *config = [[WKWebViewConfiguration alloc] init];
    config.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
    self.webView = [[WKWebView alloc] initWithFrame:self.window.contentView.bounds configuration:config];
    self.webView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.webView.navigationDelegate = self; self.webView.UIDelegate = self;
    self.webView.underPageBackgroundColor = self.window.backgroundColor;
    [self.window.contentView addSubview:self.webView];
    self.loadingView = [[NSView alloc] initWithFrame:self.window.contentView.bounds];
    self.loadingView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.loadingView.wantsLayer = YES; self.loadingView.layer.backgroundColor = self.window.backgroundColor.CGColor;
    [self.window.contentView addSubview:self.loadingView];
    NSImageView *icon = [[NSImageView alloc] init];
    icon.image = self.appIcon; icon.translatesAutoresizingMaskIntoConstraints = NO;
    [self.loadingView addSubview:icon];
    NSTextField *title = [self label:@"Forever" size:30 color:[NSColor colorWithSRGBRed:.91 green:.87 blue:.80 alpha:1]];
    [self.loadingView addSubview:title];
    self.statusLabel = [self label:@"正在打开插件与角色资料…" size:14 color:[NSColor colorWithSRGBRed:.96 green:.54 blue:.25 alpha:1]];
    self.statusLabel.maximumNumberOfLines = 4; self.statusLabel.lineBreakMode = NSLineBreakByWordWrapping;
    [self.loadingView addSubview:self.statusLabel];
    self.progress = [[NSProgressIndicator alloc] init];
    self.progress.style = NSProgressIndicatorStyleSpinning; self.progress.indeterminate = YES;
    self.progress.translatesAutoresizingMaskIntoConstraints = NO;
    [self.loadingView addSubview:self.progress]; [self.progress startAnimation:nil];
    [NSLayoutConstraint activateConstraints:@[
        [icon.centerXAnchor constraintEqualToAnchor:self.loadingView.centerXAnchor],
        [icon.centerYAnchor constraintEqualToAnchor:self.loadingView.centerYAnchor constant:-80],
        [icon.widthAnchor constraintEqualToConstant:160], [icon.heightAnchor constraintEqualToConstant:160],
        [title.topAnchor constraintEqualToAnchor:icon.bottomAnchor constant:16],
        [title.centerXAnchor constraintEqualToAnchor:icon.centerXAnchor],
        [self.statusLabel.topAnchor constraintEqualToAnchor:title.bottomAnchor constant:16],
        [self.statusLabel.centerXAnchor constraintEqualToAnchor:icon.centerXAnchor],
        [self.statusLabel.widthAnchor constraintLessThanOrEqualToConstant:620],
        [self.progress.topAnchor constraintEqualToAnchor:self.statusLabel.bottomAnchor constant:22],
        [self.progress.centerXAnchor constraintEqualToAnchor:icon.centerXAnchor]
    ]];
    [self.window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
    NSString *verificationURL = [self argumentAfter:@"--verify-url"];
    if ([NSProcessInfo.processInfo.arguments containsObject:@"--verify-native"] && verificationURL) {
        NSURL *url = [NSURL URLWithString:verificationURL];
        if (![self isLocalURL:url]) { [self showFailure:@"验收地址必须为本机服务"]; return; }
        self.serviceURL = url;
        [self.webView loadRequest:[NSURLRequest requestWithURL:url]];
    } else [self startService];
}

- (BOOL)isLocalURL:(NSURL *)url {
    return [url.scheme isEqualToString:@"http"] && [@[@"127.0.0.1",@"localhost"] containsObject:url.host] &&
        url.port.integerValue >= 1024 && url.port.integerValue <= 65535;
}

- (void)showFailure:(NSString *)message {
    self.loadingView.hidden = NO; [self.progress stopAnimation:nil];
    self.statusLabel.stringValue = message;
    [self writeState:@"failed" message:message];
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"Forever 启动未完成"; alert.informativeText = message;
    [alert addButtonWithTitle:@"重试"]; [alert addButtonWithTitle:@"关闭"];
    [alert beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse response) {
        if (response == NSAlertFirstButtonReturn) [self startService];
    }];
}

- (void)startService {
    if (self.bootstrap.running) return;
    self.loadingView.hidden = NO;
    self.statusLabel.stringValue = @"正在连接本地服务与角色资料…";
    [self.progress startAnimation:nil]; [self writeState:@"starting" message:@""];
    NSURL *launcher = [self.projectURL URLByAppendingPathComponent:@"启动.command"];
    if (![[NSFileManager defaultManager] isExecutableFileAtPath:launcher.path]) {
        [self showFailure:@"没有找到项目启动入口。请保留完整项目文件夹，或重新构建应用。"]; return;
    }
    self.bootstrap = [[NSTask alloc] init];
    self.bootstrap.executableURL = [NSURL fileURLWithPath:@"/bin/sh"];
    self.bootstrap.arguments = @[launcher.path,@"--desktop",@"--no-browser",@"--emit-launch-json"];
    self.bootstrap.currentDirectoryURL = self.projectURL;
    NSPipe *pipe = [NSPipe pipe]; self.bootstrap.standardOutput = pipe; self.bootstrap.standardError = pipe;
    NSError *error;
    if (![self.bootstrap launchAndReturnError:&error]) {
        [self showFailure:error.localizedDescription]; return;
    }
    NSTask *task = self.bootstrap;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0), ^{
        NSData *output = [pipe.fileHandleForReading readDataToEndOfFile];
        [task waitUntilExit];
        NSString *text = [[NSString alloc] initWithData:output encoding:NSUTF8StringEncoding] ?: @"";
        dispatch_async(dispatch_get_main_queue(), ^{
            NSString *payload;
            for (NSString *line in [text componentsSeparatedByCharactersInSet:NSCharacterSet.newlineCharacterSet]) {
                if ([line hasPrefix:@"FOREVERAI_LAUNCH="]) payload = [line substringFromIndex:17];
            }
            id parsed = payload ? [NSJSONSerialization JSONObjectWithData:[payload dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil] : nil;
            NSDictionary *info = [parsed isKindOfClass:NSDictionary.class] ? parsed : nil;
            NSURL *url = [info[@"url"] isKindOfClass:NSString.class] ? [NSURL URLWithString:info[@"url"]] : nil;
            if (task.terminationStatus != 0 || ![self isLocalURL:url]) {
                NSString *detail = text.length > 1000 ? [text substringFromIndex:text.length-1000] : text;
                [self showFailure:detail.length ? detail : @"本地服务没有返回可用地址，请重试。"]; return;
            }
            self.serviceURL = url;
            [self.webView loadRequest:[NSURLRequest requestWithURL:url]];
        });
    });
}

- (void)webView:(WKWebView *)webView didFinishNavigation:(WKNavigation *)navigation {
    self.loadingView.hidden = YES; [self.progress stopAnimation:nil];
    [self.window makeFirstResponder:webView];
    [self writeState:@"ready" message:webView.title ?: @""];
    if ([NSProcessInfo.processInfo.arguments containsObject:@"--verify-native"]) {
        NSURL *directory = [self verificationDirectory];
        [[NSFileManager defaultManager] createDirectoryAtURL:directory withIntermediateDirectories:YES attributes:nil error:nil];
        NSString *script = @"await Promise.race([Promise.all(Array.from(document.images).filter(i=>i.loading!=='lazy').map(i=>i.complete?Promise.resolve():new Promise(r=>{i.onload=r;i.onerror=r}))),new Promise(r=>setTimeout(r,15000))]); await new Promise(r=>setTimeout(r,500)); return {title:document.title,width:innerWidth,height:innerHeight,contentWidth:document.documentElement.scrollWidth,rows:Array.from(document.querySelectorAll('[data-addon-id]')).filter(r=>r.getBoundingClientRect().bottom<=innerHeight).length,images:Array.from(document.images).map(i=>({src:i.getAttribute('src'),loaded:i.complete&&i.naturalWidth>0})),heading:document.querySelector('h1')?.innerText};";
        [webView callAsyncJavaScript:script arguments:@{} inFrame:nil inContentWorld:WKContentWorld.pageWorld completionHandler:^(id result, NSError *error) {
            NSDictionary *report = error ? @{@"error":error.localizedDescription} : result;
            NSData *json = [NSJSONSerialization dataWithJSONObject:report ?: @{} options:NSJSONWritingPrettyPrinted error:nil];
            [json writeToURL:[directory URLByAppendingPathComponent:@"layout.json"] atomically:YES];
            [webView takeSnapshotWithConfiguration:nil completionHandler:^(NSImage *image, NSError *snapshotError) {
                if (!image || snapshotError) return;
                NSBitmapImageRep *bitmap = [NSBitmapImageRep imageRepWithData:image.TIFFRepresentation];
                [[bitmap representationUsingType:NSBitmapImageFileTypePNG properties:@{}]
                    writeToURL:[directory URLByAppendingPathComponent:@"native-content.png"] atomically:YES];
            }];
        }];
    }
}
- (void)webView:(WKWebView *)webView didFailProvisionalNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    if (error.code != NSURLErrorCancelled) [self showFailure:error.localizedDescription];
}
- (void)webView:(WKWebView *)webView didFailNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    if (error.code != NSURLErrorCancelled) [self showFailure:error.localizedDescription];
}
- (void)webView:(WKWebView *)webView decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))decisionHandler {
    NSURL *url = action.request.URL;
    if ([self isLocalURL:url] && [url.port isEqual:self.serviceURL.port]) {
        decisionHandler(action.shouldPerformDownload ? WKNavigationActionPolicyDownload : WKNavigationActionPolicyAllow); return;
    }
    if (action.navigationType == WKNavigationTypeLinkActivated && [@[@"https",@"http"] containsObject:url.scheme]) {
        [NSWorkspace.sharedWorkspace openURL:url];
    }
    decisionHandler(WKNavigationActionPolicyCancel);
}
- (WKWebView *)webView:(WKWebView *)webView createWebViewWithConfiguration:(WKWebViewConfiguration *)configuration forNavigationAction:(WKNavigationAction *)action windowFeatures:(WKWindowFeatures *)windowFeatures {
    if (!action.targetFrame && [@[@"https",@"http"] containsObject:action.request.URL.scheme]) [NSWorkspace.sharedWorkspace openURL:action.request.URL];
    return nil;
}
- (void)webView:(WKWebView *)webView runOpenPanelWithParameters:(WKOpenPanelParameters *)parameters initiatedByFrame:(WKFrameInfo *)frame completionHandler:(void (^)(NSArray<NSURL *> *))completionHandler {
    NSOpenPanel *panel = [NSOpenPanel openPanel];
    panel.canChooseDirectories = NO; panel.canChooseFiles = YES; panel.allowsMultipleSelection = NO;
    panel.allowedContentTypes = @[[UTType typeWithFilenameExtension:@"zip"]];
    [panel beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse response) {
        completionHandler(response == NSModalResponseOK ? panel.URLs : nil);
    }];
}
- (void)webView:(WKWebView *)webView runJavaScriptConfirmPanelWithMessage:(NSString *)message initiatedByFrame:(WKFrameInfo *)frame completionHandler:(void (^)(BOOL))completionHandler {
    NSAlert *alert = [[NSAlert alloc] init]; alert.messageText = message;
    [alert addButtonWithTitle:@"继续"]; [alert addButtonWithTitle:@"取消"];
    [alert beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse response) {
        completionHandler(response == NSAlertFirstButtonReturn);
    }];
}
- (void)webView:(WKWebView *)webView decidePolicyForNavigationResponse:(WKNavigationResponse *)response decisionHandler:(void (^)(WKNavigationResponsePolicy))decisionHandler {
    if (![self isLocalURL:response.response.URL]) { decisionHandler(WKNavigationResponsePolicyCancel); return; }
    decisionHandler(response.canShowMIMEType ? WKNavigationResponsePolicyAllow : WKNavigationResponsePolicyDownload);
}
- (void)webView:(WKWebView *)webView navigationAction:(WKNavigationAction *)action didBecomeDownload:(WKDownload *)download { download.delegate = self; }
- (void)webView:(WKWebView *)webView navigationResponse:(WKNavigationResponse *)response didBecomeDownload:(WKDownload *)download { download.delegate = self; }
- (void)download:(WKDownload *)download decideDestinationUsingResponse:(NSURLResponse *)response suggestedFilename:(NSString *)filename completionHandler:(void (^)(NSURL *))completionHandler {
    NSSavePanel *panel = [NSSavePanel savePanel]; panel.nameFieldStringValue = filename;
    [panel beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse result) {
        completionHandler(result == NSModalResponseOK ? panel.URL : nil);
    }];
}
- (void)download:(WKDownload *)download didFailWithError:(NSError *)error resumeData:(NSData *)resumeData {
    [self writeState:@"download_failed" message:error.localizedDescription];
}
- (void)downloadDidFinish:(WKDownload *)download { [self writeState:@"ready" message:@"ZIP 已保存"]; }
- (void)refresh:(id)sender { if (self.serviceURL) [self.webView reload]; else [self startService]; }
- (void)goHome:(id)sender { if (self.serviceURL) [self.webView loadRequest:[NSURLRequest requestWithURL:self.serviceURL]]; }
- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)flag {
    [self.window makeKeyAndOrderFront:nil]; return YES;
}
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender { return YES; }
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSApplication *app = NSApplication.sharedApplication;
        [app setActivationPolicy:NSApplicationActivationPolicyRegular];
        __attribute__((objc_precise_lifetime)) ForeverApp *delegate = [[ForeverApp alloc] init];
        app.delegate = delegate;
        [app run];
    }
    return 0;
}
