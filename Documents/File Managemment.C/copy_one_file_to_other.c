#include<stdio.h>
#include<stdlib.h>
int main()
{
    FILE *fp1,*fp2;
    fp1=fopen("a.txt","r");
    fp2=fopen("des.txt","a+");
    char ch;
    while((ch=fgetc(fp1))!=EOF)
    {
        fputc(ch,fp2);
    }
    rewind(fp2);
    while(!feof(fp2))
    {
        ch=fgetc(fp2);
        printf("%c",ch);
    }
    return 0;
}