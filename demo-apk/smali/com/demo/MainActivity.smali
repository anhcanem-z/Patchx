.class public Lcom/demo/MainActivity;

.method protected onCreate(Landroid/os/Bundle;)V
    .registers 5

    const-string v0, "android_id"

    invoke-static {v0, v1}, Landroid/provider/Settings$Secure;->getString(Landroid/content/ContentResolver;Ljava/lang/String;)Ljava/lang/String;

    move-result-object v0
    return-void
.end method
