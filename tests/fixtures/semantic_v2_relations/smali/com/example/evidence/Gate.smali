.class public Lcom/example/evidence/Gate;
.super Ljava/lang/Object;

.field private static enabled:Z

.method public static isEnabled()Z
    .registers 1
    sget-boolean v0, Lcom/example/evidence/Gate;->enabled:Z
    return v0
.end method

.method public static setEnabled(Z)V
    .registers 1
    sput-boolean p0, Lcom/example/evidence/Gate;->enabled:Z
    return-void
.end method
