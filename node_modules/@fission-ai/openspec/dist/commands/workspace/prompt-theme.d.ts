export declare const workspacePromptTheme: {
    prefix: string;
    style: {
        answer: (text: string) => string;
        defaultAnswer: (text: string) => string;
        error: (text: string) => string;
        help: (text: string) => string;
        highlight: (text: string) => string;
        key: (text: string) => string;
        message: (text: string) => string;
    };
};
export declare const workspaceSelectTheme: {
    icon: {
        cursor: string;
    };
    style: {
        keysHelpTip: (keys: [key: string, action: string][]) => string;
        answer: (text: string) => string;
        defaultAnswer: (text: string) => string;
        error: (text: string) => string;
        help: (text: string) => string;
        highlight: (text: string) => string;
        key: (text: string) => string;
        message: (text: string) => string;
    };
    prefix: string;
};
//# sourceMappingURL=prompt-theme.d.ts.map