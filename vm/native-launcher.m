/* Guest-only responsive AppKit parent. Never starts the chat brain. */
#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>
#import <CoreGraphics/CoreGraphics.h>
#include <errno.h>
#include <libproc.h>
#include <limits.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/sysctl.h>
#include <sys/stat.h>
#include <unistd.h>

static BOOL IsGuest(void) {
    char model[128] = {0}; size_t length = sizeof(model);
    return sysctlbyname("hw.model", model, &length, NULL, 0) == 0 &&
           strncmp(model, "VirtualMac", 10) == 0 && getuid() != 0;
}

@interface BaguetteDelegate : NSObject <NSApplicationDelegate, NSWindowDelegate>
@property(strong) NSWindow *window;
@property(strong) NSTextField *bridgeLabel;
@property(strong) NSTextField *permissionLabel;
@property(strong) NSTextField *detailLabel;
@property(strong) NSTextView *logView;
@property(strong) NSButton *startButton;
@property(strong) NSButton *stopButton;
@property(strong) NSTask *launcherTask;
@property(strong) NSTimer *timer;
@property(copy) NSString *root;
@property(assign) BOOL quitting;
@property(assign) BOOL requestingPermissions;
@property(strong) NSDate *restartDeadline;
@property(assign) BOOL requestPermissionsOnReady;
@property(assign) BOOL eventLoopReady;
@property(assign) NSUInteger eventLoopTicks;
@property(assign) BOOL receiptErrorReported;
@end

@implementation BaguetteDelegate
- (NSString *)path:(NSString *)relative { return [self.root stringByAppendingPathComponent:relative]; }
- (pid_t)pidFrom:(NSString *)relative {
    NSString *value = [NSString stringWithContentsOfFile:[self path:relative] encoding:NSUTF8StringEncoding error:NULL];
    NSString *trimmed = [value stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    if (!trimmed.length || trimmed.length > 10 || [trimmed rangeOfCharacterFromSet:NSCharacterSet.decimalDigitCharacterSet.invertedSet].location != NSNotFound) return 0;
    long long number = trimmed.longLongValue;
    return number > 1 && number <= INT_MAX ? (pid_t)number : 0;
}
- (BOOL)alive:(pid_t)pid { return pid > 1 && (kill(pid, 0) == 0 || errno == EPERM); }
- (BOOL)verifiedAgent:(pid_t)pid {
    if (![self alive:pid]) return NO;
    char executable[PROC_PIDPATHINFO_MAXSIZE] = {0}; struct proc_bsdinfo info;
    if (proc_pidpath(pid, executable, sizeof(executable)) <= 0 || proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, sizeof(info)) != sizeof(info) || info.pbi_uid != getuid()) return NO;
    NSString *actual = [[NSString stringWithUTF8String:executable] stringByResolvingSymlinksInPath];
    return [actual isEqualToString:[[self path:@"bin/tart-guest-agent"] stringByResolvingSymlinksInPath]];
}
- (void)note:(NSString *)message {
    if (!message.length) return;
    NSString *stamp = [NSDateFormatter localizedStringFromDate:NSDate.date dateStyle:NSDateFormatterNoStyle timeStyle:NSDateFormatterMediumStyle];
    [self.logView.textStorage appendAttributedString:[[NSAttributedString alloc] initWithString:[NSString stringWithFormat:@"%@  %@\n", stamp, message]]];
    if (self.logView.string.length > 24000) [self.logView.textStorage deleteCharactersInRange:NSMakeRange(0, self.logView.string.length - 24000)];
    [self.logView scrollRangeToVisible:NSMakeRange(self.logView.string.length, 0)];
    self.detailLabel.stringValue = message;
}
- (NSButton *)button:(NSString *)title action:(SEL)action { return [NSButton buttonWithTitle:title target:self action:action]; }
- (void)buildWindow {
    self.window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 700, 450) styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable backing:NSBackingStoreBuffered defer:NO];
    self.window.title = @"大肥鱼 · 微信桥接"; self.window.delegate = self; self.window.releasedWhenClosed = NO;
    self.window.minSize = NSMakeSize(680, 420); [self.window center];
    NSTextField *heading = [NSTextField labelWithString:@"大肥鱼 · 微信桥接"];
    heading.font = [NSFont systemFontOfSize:22 weight:NSFontWeightSemibold];
    NSTextField *explanation = [NSTextField wrappingLabelWithString:@"此窗口管理虚拟机内的连接和权限。聊天开关与人格设置在主机控制台。"];
    self.bridgeLabel = [NSTextField labelWithString:@"正在检查连接状态…"];
    self.bridgeLabel.font = [NSFont systemFontOfSize:15 weight:NSFontWeightMedium];
    self.permissionLabel = [NSTextField wrappingLabelWithString:@"正在检查应用权限…"];
    self.detailLabel = [NSTextField wrappingLabelWithString:@"此窗口不会登录、读取或发送聊天消息。"];
    self.detailLabel.textColor = NSColor.secondaryLabelColor;
    self.startButton = [self button:@"启动连接" action:@selector(startBridge:)];
    self.stopButton = [self button:@"停止连接" action:@selector(stopBridge:)];
    NSStackView *buttons = [NSStackView stackViewWithViews:@[[self button:@"打开微信" action:@selector(openWeChat:)], [self button:@"检查权限" action:@selector(requestPermissions:)], self.startButton, self.stopButton, [self button:@"重启连接" action:@selector(restartBridge:)], [self button:@"查看日志" action:@selector(showLog:)]]];
    buttons.orientation = NSUserInterfaceLayoutOrientationHorizontal; buttons.spacing = 8;
    NSScrollView *scroll = [[NSScrollView alloc] initWithFrame:NSZeroRect]; scroll.hasVerticalScroller = YES; scroll.borderType = NSBezelBorder;
    self.logView = [[NSTextView alloc] initWithFrame:NSMakeRect(0, 0, 640, 150)]; self.logView.editable = NO;
    self.logView.font = [NSFont monospacedSystemFontOfSize:11 weight:NSFontWeightRegular];
    self.logView.autoresizingMask = NSViewWidthSizable; self.logView.textContainer.widthTracksTextView = YES; scroll.documentView = self.logView;
    NSStackView *stack = [NSStackView stackViewWithViews:@[heading, explanation, self.bridgeLabel, self.permissionLabel, buttons, self.detailLabel, scroll]];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical; stack.alignment = NSLayoutAttributeLeading; stack.spacing = 14; stack.translatesAutoresizingMaskIntoConstraints = NO;
    [self.window.contentView addSubview:stack]; NSView *content = self.window.contentView;
    [NSLayoutConstraint activateConstraints:@[[stack.leadingAnchor constraintEqualToAnchor:content.leadingAnchor constant:24], [stack.trailingAnchor constraintEqualToAnchor:content.trailingAnchor constant:-24], [stack.topAnchor constraintEqualToAnchor:content.topAnchor constant:22], [stack.bottomAnchor constraintEqualToAnchor:content.bottomAnchor constant:-22], [scroll.widthAnchor constraintEqualToAnchor:stack.widthAnchor], [scroll.heightAnchor constraintGreaterThanOrEqualToConstant:100], [explanation.widthAnchor constraintEqualToAnchor:stack.widthAnchor], [self.permissionLabel.widthAnchor constraintEqualToAnchor:stack.widthAnchor], [self.detailLabel.widthAnchor constraintEqualToAnchor:stack.widthAnchor]]];
}
- (void)buildMenu {
    NSMenu *menu = [[NSMenu alloc] initWithTitle:@"Main"];
    NSMenuItem *appItem = [[NSMenuItem alloc] initWithTitle:@"大肥鱼" action:NULL keyEquivalent:@""];
    NSMenu *appMenu = [[NSMenu alloc] initWithTitle:@"大肥鱼"];
    NSArray *entries = @[@[@"显示状态窗口", NSStringFromSelector(@selector(showWindow:)), @"1"], @[@"打开微信", NSStringFromSelector(@selector(openWeChat:)), @"w"], @[@"检查权限", NSStringFromSelector(@selector(requestPermissions:)), @","], @[@"刷新状态", NSStringFromSelector(@selector(refreshAction:)), @"r"], @[@"查看日志", NSStringFromSelector(@selector(showLog:)), @"l"]];
    for (NSArray *entry in entries) { NSMenuItem *item = [[NSMenuItem alloc] initWithTitle:entry[0] action:NSSelectorFromString(entry[1]) keyEquivalent:entry[2]]; item.target = self; [appMenu addItem:item]; }
    [appMenu addItem:NSMenuItem.separatorItem];
    [appMenu addItem:[[NSMenuItem alloc] initWithTitle:@"退出大肥鱼" action:@selector(terminate:) keyEquivalent:@"q"]];
    appItem.submenu = appMenu; [menu addItem:appItem]; NSApp.mainMenu = menu;
}
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    (void)notification; self.root = [NSHomeDirectory() stringByAppendingPathComponent:@"baguette"];
    self.requestPermissionsOnReady = [NSProcessInfo.processInfo.arguments containsObject:@"--request-permissions"];
    [self buildMenu]; [self buildWindow]; [self showWindow:nil];
    [self note:@"窗口已就绪。先检查现有连接，不会创建重复进程。"];
    [self refresh]; __weak BaguetteDelegate *weakSelf = self;
    self.timer = [NSTimer scheduledTimerWithTimeInterval:2 repeats:YES block:^(NSTimer *timer) { (void)timer; weakSelf.eventLoopTicks += 1; [weakSelf refresh]; }];
    dispatch_async(dispatch_get_main_queue(), ^{ weakSelf.eventLoopReady = YES; [weakSelf startBridge:nil]; });
}
- (BOOL)applicationShouldHandleReopen:(NSApplication *)app hasVisibleWindows:(BOOL)visible { (void)app; (void)visible; [self showWindow:nil]; return YES; }
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)app { (void)app; return NO; }
- (void)showWindow:(id)sender { (void)sender; [self.window makeKeyAndOrderFront:nil]; [NSApp activateIgnoringOtherApps:YES]; }
- (void)refresh {
    pid_t pid = [self pidFrom:@"runtime/guest-agent.pid"]; BOOL verified = [self verifiedAgent:pid];
    self.bridgeLabel.stringValue = verified ? [NSString stringWithFormat:@"连接进程正在运行 · PID %d", pid] : self.launcherTask.running ? @"正在启动连接…" : @"连接尚未运行";
    self.bridgeLabel.textColor = verified ? NSColor.systemGreenColor : NSColor.systemOrangeColor;
    self.permissionLabel.stringValue = [NSString stringWithFormat:@"当前应用权限：辅助功能 %@  ·  屏幕录制 %@\n实际聊天适配器的权限由主机只读状态检查另行核实。", AXIsProcessTrusted() ? @"已允许" : @"未允许", CGPreflightScreenCaptureAccess() ? @"已允许" : @"未允许"];
    self.startButton.enabled = !verified && !self.launcherTask.running; self.stopButton.enabled = verified || self.launcherTask.running;
    NSDictionary *receipt = @{@"app_pid": @(getpid()), @"eventloop_ready": @(self.eventLoopReady),
        @"eventloop_ticks": @(self.eventLoopTicks), @"observed_at": @(NSDate.date.timeIntervalSince1970),
        @"native_permissions": @{@"accessibility": @(AXIsProcessTrusted()), @"screen_recording": @(CGPreflightScreenCaptureAccess())},
        @"agent_process_verified": @(verified), @"verified_agent_pid": verified ? @(pid) : NSNull.null,
        @"launcher_child_pid": self.launcherTask.running ? @(self.launcherTask.processIdentifier) : NSNull.null,
        @"rpc_health": @"not_probed", @"account_identity": @"not_inspected"};
    NSError *receiptError = nil;
    NSData *receiptData = [NSJSONSerialization dataWithJSONObject:receipt options:NSJSONWritingPrettyPrinted error:&receiptError];
    NSString *receiptPath = [self path:@"runtime/native-status.json"];
    if (!receiptData || ![receiptData writeToFile:receiptPath options:NSDataWritingAtomic error:&receiptError]) {
        if (!self.receiptErrorReported) [self note:[NSString stringWithFormat:@"无法写入本地状态记录：%@", receiptError.localizedDescription ?: @"未知错误"]];
        self.receiptErrorReported = YES;
    } else {
        chmod(receiptPath.fileSystemRepresentation, 0600); self.receiptErrorReported = NO;
    }
    if (self.requestPermissionsOnReady && self.eventLoopReady && verified) {
        self.requestPermissionsOnReady = NO;
        dispatch_async(dispatch_get_main_queue(), ^{ [self requestPermissions:nil]; });
    }
    if (self.restartDeadline) {
        pid_t oldLauncher = [self pidFrom:@"runtime/guest-agent-launcher.pid"];
        if (!verified && !self.launcherTask.running && ![self alive:oldLauncher]) {
            self.restartDeadline = nil;
            dispatch_async(dispatch_get_main_queue(), ^{ [self startBridge:nil]; });
        } else if (self.restartDeadline.timeIntervalSinceNow < 0) {
            self.restartDeadline = nil;
            [self note:@"旧连接未在预期时间内退出，未启动第二个进程。请查看日志。"];
        }
    }
}
- (void)refreshAction:(id)sender { (void)sender; [self refresh]; }
- (void)startBridge:(id)sender {
    (void)sender;
    if ([self verifiedAgent:[self pidFrom:@"runtime/guest-agent.pid"]]) { [self note:@"已找到现有连接；保持运行，仅在窗口中显示状态。"] ; [self refresh]; return; }
    if (self.launcherTask.running) return;
    for (NSString *part in @[@"runtime/guest-attestation.json", @"guest-agent-launcher.zsh", @"bin/tart-guest-agent"]) {
        if (![NSFileManager.defaultManager fileExistsAtPath:[self path:part]]) { [self note:[NSString stringWithFormat:@"缺少 %@。请先运行虚拟机内安装程序。", part]]; [self refresh]; return; }
    }
    NSTask *task = [[NSTask alloc] init]; task.executableURL = [NSURL fileURLWithPath:@"/bin/zsh"];
    task.arguments = @[[self path:@"guest-agent-launcher.zsh"]]; task.currentDirectoryURL = [NSURL fileURLWithPath:self.root];
    NSMutableDictionary *environment = [NSProcessInfo.processInfo.environment mutableCopy];
    for (NSString *key in environment.allKeys) if ([key hasPrefix:@"DEEPSEEK_"] || [key isEqualToString:@"COMPANION_ADMIN_TOKEN"]) [environment removeObjectForKey:key];
    environment[@"DAFEIYU_SKIP_PERMISSION_PROMPTS"] = @"1"; task.environment = environment;
    NSPipe *errors = NSPipe.pipe; task.standardError = errors; task.standardOutput = [NSFileHandle fileHandleWithNullDevice];
    __weak BaguetteDelegate *weakSelf = self;
    task.terminationHandler = ^(NSTask *ended) {
        NSData *data = [errors.fileHandleForReading readDataToEndOfFile];
        NSString *detail = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] ?: @"";
        dispatch_async(dispatch_get_main_queue(), ^{
            BaguetteDelegate *owner = weakSelf; if (!owner || owner.quitting) return;
            if ([owner verifiedAgent:[owner pidFrom:@"runtime/guest-agent.pid"]]) [owner note:@"启动器退出后仍检测到现有连接，保持该连接。"];
            else if (ended.terminationStatus != 0) { NSString *bounded = detail.length > 500 ? [detail substringToIndex:500] : detail; [owner note:[NSString stringWithFormat:@"启动器已退出（代码 %d）。%@ 请查看日志，未自动重试。", ended.terminationStatus, bounded]]; }
            else [owner note:@"连接已停止。微信仍可独立使用。"];
            [owner refresh];
        });
    };
    NSError *error = nil;
    if (![task launchAndReturnError:&error]) { [self note:[NSString stringWithFormat:@"无法启动连接：%@", error.localizedDescription]]; return; }
    self.launcherTask = task; [self note:@"已启动连接。可点击「检查权限」核实此应用权限。"] ; [self refresh];
}
- (void)stopBridge:(id)sender {
    if (sender) self.restartDeadline = nil;
    if (self.launcherTask.running) { [self.launcherTask terminate]; [self note:@"已请求停止本窗口启动的连接；不会退出微信。"] ; }
    else { pid_t pid = [self pidFrom:@"runtime/guest-agent.pid"]; if ([self verifiedAgent:pid]) { if (kill(pid, SIGTERM) == 0) [self note:@"已请求停止核实过路径和用户的连接进程。"] ; else [self note:@"未能停止连接，请查看日志。"] ; } else [self note:@"没有可安全停止的连接进程，未向其他进程发送信号。"] ; }
    [self refresh];
}
- (void)restartBridge:(id)sender {
    (void)sender;
    self.restartDeadline = [NSDate dateWithTimeIntervalSinceNow:20];
    [self stopBridge:nil];
    [self note:@"已请求重启连接；窗口会等待旧进程退出后再启动。主机连接会短暂中断。"];
}
- (void)openWeChat:(id)sender {
    (void)sender;
    NSString *path = [NSHomeDirectory() stringByAppendingPathComponent:@"Applications/WeChat.app"];
    if (![NSFileManager.defaultManager fileExistsAtPath:path]) path = @"/Applications/WeChat.app";
    if (![NSFileManager.defaultManager fileExistsAtPath:path]) { [self note:@"此虚拟机没有找到微信，请运行安装盘中的安装程序。"] ; return; }
    [NSWorkspace.sharedWorkspace openApplicationAtURL:[NSURL fileURLWithPath:path] configuration:NSWorkspaceOpenConfiguration.configuration completionHandler:^(NSRunningApplication *application, NSError *error) { (void)application; if (error) dispatch_async(dispatch_get_main_queue(), ^{ [self note:[NSString stringWithFormat:@"微信未能打开：%@", error.localizedDescription]]; }); }];
}
- (void)requestPermissions:(id)sender {
    (void)sender;
    if (self.requestingPermissions) return;
    self.requestingPermissions = YES;
    [self note:@"正在请求权限；连接进程保持运行，窗口仍可使用。"];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        if (!AXIsProcessTrusted()) AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)@{(__bridge NSString *)kAXTrustedCheckOptionPrompt: @YES});
        if (!CGPreflightScreenCaptureAccess()) CGRequestScreenCaptureAccess();
        dispatch_async(dispatch_get_main_queue(), ^{
            self.requestingPermissions = NO;
            [self note:@"请在虚拟机系统设置中允许「Baguette／大肥鱼」。若要求重新打开应用，请先暂停主机聊天。"];
            [self refresh];
        });
    });
}
- (void)showLog:(id)sender {
    (void)sender; NSURL *url = [NSURL fileURLWithPath:[self path:@"runtime/guest-agent.log"]];
    if ([NSFileManager.defaultManager fileExistsAtPath:url.path]) [NSWorkspace.sharedWorkspace activateFileViewerSelectingURLs:@[url]];
    else [self note:@"日志尚未创建；启动错误会显示在此窗口。"] ;
}
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)app {
    (void)app;
    if ([self verifiedAgent:[self pidFrom:@"runtime/guest-agent.pid"]] || self.launcherTask.running) {
        NSAlert *alert = [[NSAlert alloc] init]; alert.messageText = @"停止连接并退出大肥鱼？"; alert.informativeText = @"主机将暂时无法连接虚拟机。微信应用会继续保留。";
        [alert addButtonWithTitle:@"继续运行"]; [alert addButtonWithTitle:@"停止并退出"];
        if ([alert runModal] != NSAlertSecondButtonReturn) return NSTerminateCancel;
        [self stopBridge:nil];
    }
    self.quitting = YES; [self.timer invalidate]; return NSTerminateNow;
}
@end

int main(void) {
    /* Guard before AppKit initializes any application or GUI state. */
    if (!IsGuest()) { fputs("Baguette runs only as the logged-in user of its macOS virtual machine.\n", stderr); return 1; }
    @autoreleasepool {
        NSApplication *application = NSApplication.sharedApplication;
        application.activationPolicy = NSApplicationActivationPolicyRegular;
        __attribute__((objc_precise_lifetime)) BaguetteDelegate *delegate = [[BaguetteDelegate alloc] init];
        application.delegate = delegate;
        [application run];
    }
    return 0;
}
