#include<stdio.h>
#include<stdlib.h>
int main()
{
    FILE *fp;
    fp=fopen("a.txt","r+");
    char s[10];
    fputs("jenny",fp);
    fputc(' ',fp);
    fclose(fp);
    return 0;
}